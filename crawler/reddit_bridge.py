"""Reddit 公开 JSON 页面采集桥接器。

当前实现只读取配置中明确列出的 subreddit ``new.json`` 页面，再在本地执行
关键词、时间窗口和帖子 ID 过滤。不使用 OAuth、PRAW、登录 Cookie、RSS 或代理轮换。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Set, Tuple
from urllib.parse import quote, urlparse
from uuid import uuid4

import config
from crawler.base import CrawlRunResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PLATFORMS = {"reddit"}
SUBREDDIT_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class RedditJsonError(RuntimeError):
    """Reddit JSON 请求或响应无法继续处理。"""


def _resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _clean_subreddit(value: object) -> str:
    subreddit = str(value).strip()
    if subreddit.casefold().startswith("r/"):
        subreddit = subreddit[2:]
    return subreddit


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


class RedditBridge:
    """采集 subreddit 最新 JSON，输出项目现有的内容 JSONL。"""

    def __init__(
        self,
        requester: Optional[Callable[..., object]] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.platform = "reddit"
        self.configured_platform = str(config.CRAWL_PLATFORM).strip().casefold()
        self.keywords = [str(keyword).strip() for keyword in config.SEARCH_KEYWORDS]
        raw_subreddits = getattr(config, "REDDIT_SUBREDDITS", [])
        if isinstance(raw_subreddits, str):
            raw_subreddits = [raw_subreddits]
        self.subreddits = [
            _clean_subreddit(subreddit) for subreddit in raw_subreddits
        ]
        self.limit = getattr(config, "CRAWL_LIMIT", 20)
        self.per_subreddit_limit = getattr(
            config, "REDDIT_RESULTS_PER_SUBREDDIT", 50
        )
        self.lookback_hours = getattr(config, "REDDIT_LOOKBACK_HOURS", 168)
        self.request_timeout = getattr(
            config, "REDDIT_REQUEST_TIMEOUT_SECONDS", 30
        )
        self.user_agent = str(getattr(config, "REDDIT_USER_AGENT", "")).strip()
        self.base_url = str(
            getattr(config, "REDDIT_BASE_URL", "https://www.reddit.com")
        ).strip().rstrip("/")
        self.state_file = _resolve_project_path(config.REDDIT_STATE_FILE)
        self.seen_id_limit = getattr(config, "REDDIT_SEEN_ID_LIMIT", 5000)
        self.target_data_dir = _resolve_project_path(config.DATA_DIR)
        self._requester = requester
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._pending_ids: Tuple[str, ...] = ()

    def validate(self) -> List[str]:
        """返回阻止 Reddit JSON 采集启动的配置错误。"""
        errors: List[str] = []

        if self.configured_platform not in SUPPORTED_PLATFORMS:
            errors.append(
                f"CRAWL_PLATFORM={config.CRAWL_PLATFORM!r} 不能由 Reddit JSON "
                "采集器处理；请使用 reddit"
            )
        if not self.keywords or any(not keyword for keyword in self.keywords):
            errors.append("SEARCH_KEYWORDS 必须至少包含一个非空关键词")
        if not self.subreddits or any(not subreddit for subreddit in self.subreddits):
            errors.append("REDDIT_SUBREDDITS 必须至少包含一个明确的 subreddit")
        for subreddit in self.subreddits:
            if subreddit.casefold() == "all":
                errors.append(
                    "REDDIT_SUBREDDITS 不使用 all；请列出需要监控的明确社区"
                )
            elif not SUBREDDIT_PATTERN.fullmatch(subreddit):
                errors.append(
                    f"REDDIT_SUBREDDITS 包含无效社区名称：{subreddit!r}"
                )
        if not isinstance(self.limit, int) or self.limit <= 0:
            errors.append("CRAWL_LIMIT 必须是正整数")
        if (
            not isinstance(self.per_subreddit_limit, int)
            or not 1 <= self.per_subreddit_limit <= 100
        ):
            errors.append("REDDIT_RESULTS_PER_SUBREDDIT 必须在 1 到 100 之间")
        if (
            not isinstance(self.lookback_hours, (int, float))
            or self.lookback_hours <= 0
        ):
            errors.append("REDDIT_LOOKBACK_HOURS 必须大于 0")
        if (
            not isinstance(self.request_timeout, (int, float))
            or self.request_timeout <= 0
        ):
            errors.append("REDDIT_REQUEST_TIMEOUT_SECONDS 必须大于 0")
        if not isinstance(self.seen_id_limit, int) or self.seen_id_limit <= 0:
            errors.append("REDDIT_SEEN_ID_LIMIT 必须是正整数")
        if not self.user_agent or self.user_agent.casefold() in {
            "your-user-agent",
            "change-me",
        }:
            errors.append("REDDIT_USER_AGENT 必须如实标识本项目")

        parsed_base_url = urlparse(self.base_url)
        if (
            parsed_base_url.scheme not in {"http", "https"}
            or not parsed_base_url.netloc
        ):
            errors.append("REDDIT_BASE_URL 必须是有效的 http/https URL")

        state_error = self._state_error()
        if state_error:
            errors.append(state_error)
        return errors

    def run(self) -> CrawlRunResult:
        """执行一次 Reddit JSON 采集并写入本次运行的 JSONL。"""
        errors = self.validate()
        if errors:
            return CrawlRunResult(success=False, error="；".join(errors))

        now = self._as_utc(self._now_provider())
        run_id = f"{now:%Y%m%dT%H%M%S%f}-{uuid4().hex[:8]}"
        output_dir = self.target_data_dir / "crawler_runs" / run_id
        content_dir = output_dir / self.platform / "jsonl"
        output_file = content_dir / f"search_contents_{now:%Y-%m-%d}.jsonl"
        self._pending_ids = ()

        print(f"Reddit JSON 社区：{', '.join(self.subreddits)}")
        print(f"Reddit 本地关键词：{', '.join(self.keywords)}")
        print(f"Reddit 本次输出：{output_dir}")

        try:
            rows = self._collect(now)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Reddit JSON 采集失败：{type(exc).__name__}: {exc}",
            )
        except Exception as exc:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Reddit JSON 请求失败：{type(exc).__name__}: {exc}",
            )

        if not rows:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error="Reddit JSON 请求完成，但本次没有匹配的新内容",
            )

        try:
            content_dir.mkdir(parents=True, exist_ok=True)
            temporary_file = output_file.with_suffix(".jsonl.tmp")
            with temporary_file.open("w", encoding="utf-8") as file_obj:
                for row in rows:
                    file_obj.write(json.dumps(row, ensure_ascii=False) + "\n")
            temporary_file.replace(output_file)
        except OSError as exc:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Reddit 数据写入失败：{exc}",
            )

        self._pending_ids = tuple(str(row["id"]) for row in rows)
        return CrawlRunResult(
            success=True,
            data_files=(output_file,),
            output_dir=output_dir,
            returncode=0,
        )

    def acknowledge(self) -> str:
        """完整工作流成功后再记录已处理帖子 ID。"""
        if not self._pending_ids:
            return ""
        try:
            existing = self._load_seen_ids()
            ordered_ids = list(existing)
            ordered_ids.extend(
                post_id for post_id in self._pending_ids if post_id not in existing
            )
            ordered_ids = ordered_ids[-self.seen_id_limit :]
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary_file = self.state_file.with_suffix(
                self.state_file.suffix + ".tmp"
            )
            temporary_file.write_text(
                json.dumps(
                    {"version": 1, "seen_ids": ordered_ids},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary_file.replace(self.state_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return f"无法保存 Reddit 已处理状态：{exc}"
        self._pending_ids = ()
        return ""

    def _collect(self, now: datetime) -> List[Dict[str, object]]:
        seen_ids = set(self._load_seen_ids())
        current_ids: Set[str] = set()
        collected: List[Tuple[float, Dict[str, object]]] = []
        cutoff = now - timedelta(hours=float(self.lookback_hours))
        failures: List[str] = []
        successful_fetches = 0

        for subreddit_name in self.subreddits:
            try:
                posts = self._fetch_subreddit(subreddit_name)
            except RedditJsonError as exc:
                failures.append(str(exc))
                continue

            successful_fetches += 1
            for post in posts:
                row = self._post_to_row(
                    post,
                    subreddit_scope=subreddit_name,
                    cutoff=cutoff,
                )
                if row is None:
                    continue
                post_id = str(row["id"])
                if post_id in seen_ids or post_id in current_ids:
                    continue
                current_ids.add(post_id)
                sort_time = float(row.pop("_sort_time"))
                collected.append((sort_time, row))

        if not successful_fetches and failures:
            raise RedditJsonError("；".join(failures))
        for failure in failures:
            print(f"Reddit JSON 跳过：{failure}")

        collected.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in collected[: self.limit]]

    def _fetch_subreddit(self, subreddit_name: str) -> List[Mapping[str, object]]:
        url = (
            f"{self.base_url}/r/"
            f"{quote(subreddit_name, safe='')}/new.json"
        )
        requester = self._requester
        request_error_types: Tuple[type, ...] = (OSError,)
        if requester is None:
            try:
                import requests
            except ImportError as exc:
                raise RedditJsonError(
                    "缺少 requests；请运行 "
                    "python3 -m pip install -r requirements.txt"
                ) from exc
            requester = requests.get
            request_error_types = (requests.RequestException,)

        try:
            response = requester(
                url,
                params={
                    "limit": self.per_subreddit_limit,
                    "raw_json": 1,
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.user_agent,
                },
                timeout=float(self.request_timeout),
            )
        except request_error_types as exc:
            raise RedditJsonError(
                f"r/{subreddit_name} 网络请求失败：{exc}"
            ) from exc

        status_code = _as_int(getattr(response, "status_code", 0))
        if status_code == 429:
            headers = getattr(response, "headers", {})
            retry_after = (
                str(headers.get("Retry-After", "")).strip()
                if isinstance(headers, Mapping)
                else ""
            )
            suffix = f"，Retry-After={retry_after}" if retry_after else ""
            raise RedditJsonError(f"r/{subreddit_name} 被限流（429）{suffix}")
        if status_code == 403:
            raise RedditJsonError(f"r/{subreddit_name} 被拒绝访问（403）")
        if status_code != 200:
            raise RedditJsonError(
                f"r/{subreddit_name} 返回 HTTP {status_code or '未知状态'}"
            )

        try:
            payload = getattr(response, "json")()
        except (TypeError, ValueError) as exc:
            raise RedditJsonError(
                f"r/{subreddit_name} 未返回合法 JSON"
            ) from exc

        if not isinstance(payload, Mapping):
            raise RedditJsonError(f"r/{subreddit_name} JSON 顶层结构无效")
        listing_data = payload.get("data")
        if not isinstance(listing_data, Mapping):
            raise RedditJsonError(f"r/{subreddit_name} JSON 缺少 data")
        children = listing_data.get("children")
        if not isinstance(children, list):
            raise RedditJsonError(f"r/{subreddit_name} JSON 缺少 children")

        posts: List[Mapping[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping) or child.get("kind") != "t3":
                continue
            post = child.get("data")
            if isinstance(post, Mapping):
                posts.append(post)
        return posts

    def _post_to_row(
        self,
        post: Mapping[str, object],
        subreddit_scope: str,
        cutoff: datetime,
    ) -> Optional[Dict[str, object]]:
        post_id = str(post.get("id", "") or "").strip()
        title = str(post.get("title", "") or "").strip()
        if not post_id or not title:
            return None

        try:
            created_utc = float(post.get("created_utc", 0) or 0)
            published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        except (OSError, OverflowError, TypeError, ValueError):
            return None
        if published_at < self._as_utc(cutoff):
            return None

        body = str(post.get("selftext", "") or "").strip()
        searchable_text = f"{title}\n{body}".casefold()
        matched_keywords = [
            keyword
            for keyword in self.keywords
            if keyword.casefold() in searchable_text
        ]
        if not matched_keywords:
            return None

        permalink = str(post.get("permalink", "") or "").strip()
        reddit_url = (
            f"https://www.reddit.com{permalink}"
            if permalink.startswith("/")
            else permalink
        )
        external_url = str(
            post.get("url_overridden_by_dest") or post.get("url") or ""
        ).strip()
        if not reddit_url:
            reddit_url = external_url

        return {
            "id": post_id,
            "title": title,
            "content": body or title,
            "source": "Reddit",
            "url": reddit_url,
            "external_url": external_url,
            "author": str(post.get("author", "") or "[deleted]").strip(),
            "publish_time": published_at.isoformat(),
            "subreddit": str(post.get("subreddit", "") or subreddit_scope).strip(),
            "score": _as_int(post.get("score")),
            "upvote_ratio": _as_float(post.get("upvote_ratio")),
            "comment_count": _as_int(post.get("num_comments")),
            "is_self": bool(post.get("is_self", False)),
            "over_18": bool(post.get("over_18", False)),
            "link_flair_text": str(post.get("link_flair_text", "") or ""),
            "domain": str(post.get("domain", "") or ""),
            "matched_keywords": matched_keywords,
            "search_keyword": matched_keywords[0],
            "search_subreddit": subreddit_scope,
            "collection_method": "reddit_json",
            "_sort_time": published_at.timestamp(),
        }

    def _state_error(self) -> str:
        if not self.state_file.exists():
            return ""
        try:
            self._load_seen_ids()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return f"Reddit 状态文件无效：{exc}"
        return ""

    def _load_seen_ids(self) -> List[str]:
        if not self.state_file.exists():
            return []
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("不支持的状态文件格式")
        seen_ids = data.get("seen_ids")
        if not isinstance(seen_ids, list) or any(
            not isinstance(post_id, str) for post_id in seen_ids
        ):
            raise ValueError("seen_ids 必须是字符串列表")
        return seen_ids

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
