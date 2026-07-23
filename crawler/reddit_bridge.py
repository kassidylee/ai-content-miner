"""PRAW Reddit 关键词搜索桥接器。

当前实现直接对齐 ``praw==8.0.2`` 的只读接口。认证信息仅从环境变量
映射到 ``config.py``，不保存 Reddit 密码、OAuth Token 或本地 Cookie。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import config
from crawler.base import CrawlRunResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PLATFORMS = {"reddit"}
SUPPORTED_SORTS = {"relevance", "hot", "top", "new", "comments"}
SUPPORTED_TIME_FILTERS = {"all", "hour", "day", "week", "month", "year"}
MINIMUM_PYTHON = (3, 10)


def _resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _safe_attr(obj: object, name: str, default: object = None) -> object:
    try:
        return getattr(obj, name)
    except (AttributeError, KeyError, TypeError, ValueError):
        return default


def _clean_subreddit(value: object) -> str:
    subreddit = str(value).strip()
    if subreddit.lower().startswith("r/"):
        subreddit = subreddit[2:]
    return subreddit


class RedditBridge:
    """校验只读 API 配置、搜索 Reddit，并输出本次运行的 JSONL。"""

    def __init__(
        self,
        reddit_factory: Optional[Callable[..., object]] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.platform = "reddit"
        self.configured_platform = str(config.CRAWL_PLATFORM).strip().lower()
        self.keywords = [str(keyword).strip() for keyword in config.SEARCH_KEYWORDS]
        raw_subreddits = getattr(config, "REDDIT_SUBREDDITS", ["all"])
        if isinstance(raw_subreddits, str):
            raw_subreddits = [raw_subreddits]
        self.subreddits = [
            _clean_subreddit(subreddit)
            for subreddit in raw_subreddits
        ]
        self.limit = getattr(config, "CRAWL_LIMIT", 20)
        self.per_query_limit = getattr(config, "REDDIT_RESULTS_PER_QUERY", 20)
        self.sort = str(getattr(config, "REDDIT_SEARCH_SORT", "new")).strip().lower()
        self.time_filter = str(
            getattr(config, "REDDIT_TIME_FILTER", "week")
        ).strip().lower()
        self.lookback_hours = getattr(config, "REDDIT_LOOKBACK_HOURS", 168)
        self.request_timeout = getattr(
            config, "REDDIT_REQUEST_TIMEOUT_SECONDS", 30
        )
        self.expected_version = str(
            getattr(config, "PRAW_EXPECTED_VERSION", "8.0.2")
        )
        self.client_id = str(getattr(config, "REDDIT_CLIENT_ID", "")).strip()
        self.client_secret = str(
            getattr(config, "REDDIT_CLIENT_SECRET", "")
        ).strip()
        self.user_agent = str(getattr(config, "REDDIT_USER_AGENT", "")).strip()
        self.state_file = _resolve_project_path(config.REDDIT_STATE_FILE)
        self.seen_id_limit = getattr(config, "REDDIT_SEEN_ID_LIMIT", 5000)
        self.target_data_dir = _resolve_project_path(config.DATA_DIR)
        self._reddit_factory = reddit_factory
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._pending_ids: Tuple[str, ...] = ()

    def validate(self) -> List[str]:
        """返回阻止 Reddit 搜索启动的配置错误。"""
        errors: List[str] = []

        if self.configured_platform not in SUPPORTED_PLATFORMS:
            errors.append(
                f"CRAWL_PLATFORM={config.CRAWL_PLATFORM!r} 不能由 PRAW 处理；"
                "请使用 reddit"
            )
        if not self.keywords or any(not keyword for keyword in self.keywords):
            errors.append("SEARCH_KEYWORDS 必须至少包含一个非空关键词")
        if not self.subreddits or any(not subreddit for subreddit in self.subreddits):
            errors.append("REDDIT_SUBREDDITS 必须至少包含一个非空社区或 all")
        if sys.version_info < MINIMUM_PYTHON:
            errors.append(
                "PRAW 8.0.2 需要 Python >=3.10；"
                f"当前为 {sys.version_info.major}.{sys.version_info.minor}"
            )
        if not isinstance(self.limit, int) or self.limit <= 0:
            errors.append("CRAWL_LIMIT 必须是正整数")
        if not isinstance(self.per_query_limit, int) or self.per_query_limit <= 0:
            errors.append("REDDIT_RESULTS_PER_QUERY 必须是正整数")
        if self.sort not in SUPPORTED_SORTS:
            errors.append(
                f"REDDIT_SEARCH_SORT={self.sort!r} 不受支持；"
                "可选 relevance、hot、top、new、comments"
            )
        if self.time_filter not in SUPPORTED_TIME_FILTERS:
            errors.append(
                f"REDDIT_TIME_FILTER={self.time_filter!r} 不受支持；"
                "可选 all、hour、day、week、month、year"
            )
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

        if not self.client_id or self.client_id.lower() in {
            "your-client-id",
            "client-id",
        }:
            errors.append("缺少 REDDIT_CLIENT_ID 环境变量")
        if not self.client_secret or self.client_secret.lower() in {
            "your-client-secret",
            "client-secret",
        }:
            errors.append("缺少 REDDIT_CLIENT_SECRET 环境变量")
        if not self.user_agent or self.user_agent.lower() in {
            "your-user-agent",
            "change-me",
        }:
            errors.append("缺少 REDDIT_USER_AGENT 环境变量")

        dependency_error = self._dependency_error()
        if dependency_error:
            errors.append(dependency_error)

        state_error = self._state_error()
        if state_error:
            errors.append(state_error)
        return errors

    def run(self) -> CrawlRunResult:
        """执行只读搜索；配置、网络、权限或无数据都返回失败结果。"""
        errors = self.validate()
        if errors:
            return CrawlRunResult(success=False, error="；".join(errors))

        now = self._as_utc(self._now_provider())
        run_id = f"{now:%Y%m%dT%H%M%S%f}-{uuid4().hex[:8]}"
        output_dir = self.target_data_dir / "crawler_runs" / run_id
        content_dir = output_dir / self.platform / "jsonl"
        output_file = content_dir / f"search_contents_{now:%Y-%m-%d}.jsonl"
        self._pending_ids = ()

        print(f"   📡 Reddit 搜索排序: {self.sort}")
        print(f"   🕐 Reddit API 时间范围: {self.time_filter}")
        print(f"   📂 本次输出: {output_dir}")
        print(f"   🔎 搜索关键词: {', '.join(self.keywords)}")
        print(f"   👥 搜索社区: {', '.join(self.subreddits)}")

        try:
            rows = self._collect(now)
        except (ImportError, OSError, TypeError, ValueError, RuntimeError) as exc:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Reddit/PRAW 执行失败：{type(exc).__name__}: {exc}",
            )
        except Exception as exc:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Reddit 搜索失败：{type(exc).__name__}: {exc}",
            )

        if not rows:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error="Reddit 搜索正常完成，但本次没有新的内容",
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
        reddit = self._make_reddit()
        seen_ids = set(self._load_seen_ids())
        current_ids: Set[str] = set()
        collected: List[Tuple[float, Dict[str, object]]] = []
        cutoff = now - timedelta(hours=float(self.lookback_hours))

        for subreddit_name in self.subreddits:
            subreddit = getattr(reddit, "subreddit")(subreddit_name)
            for keyword in self.keywords:
                submissions = getattr(subreddit, "search")(
                    keyword,
                    sort=self.sort,
                    time_filter=self.time_filter,
                    limit=self.per_query_limit,
                )
                for submission in submissions:
                    row = self._submission_to_row(
                        submission,
                        keyword=keyword,
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

        collected.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in collected[: self.limit]]

    def _submission_to_row(
        self,
        submission: object,
        keyword: str,
        subreddit_scope: str,
        cutoff: datetime,
    ) -> Optional[Dict[str, object]]:
        post_id = str(_safe_attr(submission, "id", "") or "").strip()
        title = str(_safe_attr(submission, "title", "") or "").strip()
        if not post_id or not title:
            return None

        try:
            created_utc = float(_safe_attr(submission, "created_utc", 0) or 0)
            published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        except (OSError, OverflowError, TypeError, ValueError):
            return None
        if published_at < self._as_utc(cutoff):
            return None

        body = str(_safe_attr(submission, "selftext", "") or "").strip()
        content = body or title
        author_obj = _safe_attr(submission, "author")
        author = str(author_obj).strip() if author_obj is not None else "[deleted]"
        subreddit = str(_safe_attr(submission, "subreddit", "") or "").strip()
        permalink = str(_safe_attr(submission, "permalink", "") or "").strip()
        reddit_url = (
            f"https://www.reddit.com{permalink}"
            if permalink.startswith("/")
            else permalink
        )
        external_url = str(_safe_attr(submission, "url", "") or "").strip()
        if not reddit_url:
            reddit_url = external_url

        return {
            "id": post_id,
            "title": title,
            "content": content,
            "source": "Reddit",
            "url": reddit_url,
            "external_url": external_url,
            "author": author,
            "publish_time": published_at.isoformat(),
            "subreddit": subreddit,
            "score": int(_safe_attr(submission, "score", 0) or 0),
            "upvote_ratio": float(
                _safe_attr(submission, "upvote_ratio", 0.0) or 0.0
            ),
            "comment_count": int(
                _safe_attr(submission, "num_comments", 0) or 0
            ),
            "is_self": bool(_safe_attr(submission, "is_self", False)),
            "over_18": bool(_safe_attr(submission, "over_18", False)),
            "link_flair_text": str(
                _safe_attr(submission, "link_flair_text", "") or ""
            ),
            "domain": str(_safe_attr(submission, "domain", "") or ""),
            "search_keyword": keyword,
            "search_subreddit": subreddit_scope,
            "_sort_time": published_at.timestamp(),
        }

    def _make_reddit(self) -> object:
        kwargs = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "user_agent": self.user_agent,
            "requestor_kwargs": {"timeout": float(self.request_timeout)},
        }
        if self._reddit_factory is not None:
            return self._reddit_factory(**kwargs)

        import praw

        return praw.Reddit(**kwargs)

    def _dependency_error(self) -> str:
        if importlib.util.find_spec("praw") is None:
            return (
                "缺少 PRAW；请运行 "
                "python3 -m pip install -r requirements.txt"
            )
        try:
            actual_version = metadata.version("praw")
        except metadata.PackageNotFoundError:
            return "无法读取 PRAW 安装版本"
        if self.expected_version and actual_version != self.expected_version:
            return (
                "PRAW 版本不匹配："
                f"期望 {self.expected_version}，实际 {actual_version}"
            )
        return ""

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
