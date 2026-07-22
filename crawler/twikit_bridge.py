"""Twikit 关键词搜索桥接器。

当前实现直接对齐 PyPI ``twikit==2.3.3`` 的异步接口：
``Client.load_cookies``、``Client.search_tweet`` 与 ``Result.next``。
Twikit 使用 X 的内部接口而非官方 API，运行需要本地登录 Cookie。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import config
from crawler.base import CrawlRunResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PLATFORMS = {"x", "twitter", "x.com"}
SUPPORTED_PRODUCTS = {"Latest", "Top", "Media"}
REQUIRED_COOKIE_KEYS = {"auth_token", "ct0"}
MINIMUM_PYTHON = (3, 10)


def _resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _safe_attr(obj: object, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except (AttributeError, KeyError, TypeError, ValueError):
        return default


class TwikitBridge:
    """校验本地会话、搜索 X，并输出本次运行的标准 JSONL。"""

    def __init__(
        self,
        client_factory: Optional[Callable[..., object]] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.platform = "x"
        self.configured_platform = str(config.CRAWL_PLATFORM).strip().lower()
        self.keywords = [str(keyword).strip() for keyword in config.SEARCH_KEYWORDS]
        self.limit = getattr(config, "CRAWL_LIMIT", 20)
        self.per_query_limit = getattr(config, "TWIKIT_RESULTS_PER_QUERY", 20)
        self.max_pages = getattr(config, "TWIKIT_MAX_PAGES_PER_QUERY", 5)
        self.product = str(getattr(config, "TWIKIT_SEARCH_PRODUCT", "Latest"))
        self.language = str(getattr(config, "TWIKIT_LANGUAGE", "en-US"))
        self.timeout = getattr(config, "TWIKIT_TIMEOUT_SECONDS", 120)
        self.lookback_hours = getattr(config, "TWIKIT_LOOKBACK_HOURS", 168)
        self.expected_version = str(
            getattr(config, "TWIKIT_EXPECTED_VERSION", "2.3.3")
        )
        self.cookie_file = _resolve_project_path(config.TWIKIT_COOKIE_FILE)
        self.state_file = _resolve_project_path(config.TWIKIT_STATE_FILE)
        self.seen_id_limit = getattr(config, "TWIKIT_SEEN_ID_LIMIT", 5000)
        self.target_data_dir = _resolve_project_path(config.DATA_DIR)
        self._client_factory = client_factory
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._pending_ids: Tuple[str, ...] = ()

    def validate(self) -> List[str]:
        """返回阻止 Twikit 搜索启动的配置或会话错误。"""
        errors: List[str] = []

        if self.configured_platform not in SUPPORTED_PLATFORMS:
            errors.append(
                f"CRAWL_PLATFORM={config.CRAWL_PLATFORM!r} 不能由 Twikit 处理；"
                "请使用 x"
            )
        if not self.keywords or any(not keyword for keyword in self.keywords):
            errors.append("SEARCH_KEYWORDS 必须至少包含一个非空关键词")
        if sys.version_info < MINIMUM_PYTHON:
            errors.append(
                "Twikit 2.3.3 实际运行需要 Python >=3.10；"
                f"当前为 {sys.version_info.major}.{sys.version_info.minor}"
            )
        if not isinstance(self.limit, int) or self.limit <= 0:
            errors.append("CRAWL_LIMIT 必须是正整数")
        if not isinstance(self.per_query_limit, int) or self.per_query_limit <= 0:
            errors.append("TWIKIT_RESULTS_PER_QUERY 必须是正整数")
        if not isinstance(self.max_pages, int) or self.max_pages <= 0:
            errors.append("TWIKIT_MAX_PAGES_PER_QUERY 必须是正整数")
        if self.product not in SUPPORTED_PRODUCTS:
            errors.append(
                f"TWIKIT_SEARCH_PRODUCT={self.product!r} 不受支持；"
                "可选 Latest、Top、Media"
            )
        if not self.language:
            errors.append("TWIKIT_LANGUAGE 不能为空")
        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            errors.append("TWIKIT_TIMEOUT_SECONDS 必须大于 0")
        if (
            not isinstance(self.lookback_hours, (int, float))
            or self.lookback_hours <= 0
        ):
            errors.append("TWIKIT_LOOKBACK_HOURS 必须大于 0")
        if not isinstance(self.seen_id_limit, int) or self.seen_id_limit <= 0:
            errors.append("TWIKIT_SEEN_ID_LIMIT 必须是正整数")

        dependency_error = self._dependency_error()
        if dependency_error:
            errors.append(dependency_error)

        cookie_error = self._cookie_error()
        if cookie_error:
            errors.append(cookie_error)

        state_error = self._state_error()
        if state_error:
            errors.append(state_error)
        return errors

    def run(self) -> CrawlRunResult:
        """执行搜索；配置、网络、账号或无数据都会返回失败结果。"""
        errors = self.validate()
        if errors:
            return CrawlRunResult(success=False, error="；".join(errors))

        run_id = f"{datetime.now():%Y%m%dT%H%M%S%f}-{uuid4().hex[:8]}"
        output_dir = self.target_data_dir / "crawler_runs" / run_id
        content_dir = output_dir / self.platform / "jsonl"
        output_file = content_dir / f"search_contents_{datetime.now():%Y-%m-%d}.jsonl"
        self._pending_ids = ()

        print(f"   📡 Twikit 搜索模式: {self.product}")
        print(f"   📂 本次输出: {output_dir}")
        print(f"   🔎 搜索关键词: {', '.join(self.keywords)}")

        try:
            rows = asyncio.run(
                asyncio.wait_for(self._collect(), timeout=float(self.timeout))
            )
        except asyncio.TimeoutError:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Twikit 执行超时（{self.timeout} 秒）",
            )
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Twikit 执行失败：{type(exc).__name__}: {exc}",
            )
        except Exception as exc:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error=f"Twikit 搜索失败：{type(exc).__name__}: {exc}",
            )

        if not rows:
            return CrawlRunResult(
                success=False,
                output_dir=output_dir,
                error="Twikit 正常完成，但本次没有新的 X 内容",
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
                error=f"Twikit 数据写入失败：{exc}",
            )

        self._pending_ids = tuple(str(row["id"]) for row in rows)
        return CrawlRunResult(
            success=True,
            data_files=(output_file,),
            output_dir=output_dir,
            returncode=0,
        )

    def acknowledge(self) -> str:
        """完整工作流成功后再记录已处理 ID，避免推送失败时丢数据。"""
        if not self._pending_ids:
            return ""
        try:
            existing = self._load_seen_ids()
            ordered_ids = list(existing)
            ordered_ids.extend(
                tweet_id for tweet_id in self._pending_ids if tweet_id not in existing
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
            return f"无法保存 Twikit 已处理状态：{exc}"
        self._pending_ids = ()
        return ""

    async def _collect(self) -> List[Dict[str, object]]:
        client = self._make_client()
        seen_ids = set(self._load_seen_ids())
        current_ids: Set[str] = set()
        collected: List[Tuple[float, Dict[str, object]]] = []
        cutoff = self._now_provider() - timedelta(hours=float(self.lookback_hours))

        try:
            client.load_cookies(str(self.cookie_file))
            for keyword in self.keywords:
                query_rows = await self._search_keyword(client, keyword)
                for tweet in query_rows:
                    row = self._tweet_to_row(tweet, keyword, cutoff)
                    if row is None:
                        continue
                    tweet_id = str(row["id"])
                    if tweet_id in seen_ids or tweet_id in current_ids:
                        continue
                    current_ids.add(tweet_id)
                    sort_time = float(row.pop("_sort_time"))
                    collected.append((sort_time, row))
        finally:
            http_client = getattr(client, "http", None)
            close = getattr(http_client, "aclose", None)
            if close is not None:
                await close()

        collected.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in collected[: self.limit]]

    async def _search_keyword(self, client: object, keyword: str) -> List[object]:
        tweets: List[object] = []
        page_size = min(20, self.per_query_limit)
        result = await client.search_tweet(
            keyword,
            self.product,
            count=page_size,
        )

        for page_index in range(self.max_pages):
            for tweet in result:
                tweets.append(tweet)
                if len(tweets) >= self.per_query_limit:
                    return tweets

            if not result or page_index + 1 >= self.max_pages:
                break
            next_cursor = getattr(result, "next_cursor", None)
            if not next_cursor:
                break
            result = await result.next()
        return tweets

    def _tweet_to_row(
        self, tweet: object, keyword: str, cutoff: datetime
    ) -> Optional[Dict[str, object]]:
        tweet_id = str(_safe_attr(tweet, "id", "")).strip()
        content = str(
            _safe_attr(tweet, "full_text", None)
            or _safe_attr(tweet, "text", "")
        ).strip()
        if not tweet_id or not content:
            return None

        user = _safe_attr(tweet, "user")
        screen_name = str(_safe_attr(user, "screen_name", "")).strip()
        display_name = str(_safe_attr(user, "name", "")).strip()
        author = display_name or (f"@{screen_name}" if screen_name else "")
        url_user = screen_name or "i/web"

        published_at = _safe_attr(tweet, "created_at_datetime")
        if not isinstance(published_at, datetime):
            return None
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        if published_at < cutoff:
            return None
        sort_time = published_at.timestamp()
        publish_time = published_at.isoformat()

        title_line = next(
            (line.strip() for line in content.splitlines() if line.strip()),
            "X 帖子",
        )
        title = title_line[:80]

        return {
            "id": tweet_id,
            "title": title,
            "content": content,
            "source": "X (Twitter)",
            "url": f"https://x.com/{url_user}/status/{tweet_id}",
            "author": author,
            "username": screen_name,
            "publish_time": publish_time,
            "lang": str(_safe_attr(tweet, "lang", "") or ""),
            "like_count": _safe_attr(tweet, "favorite_count", 0) or 0,
            "comment_count": _safe_attr(tweet, "reply_count", 0) or 0,
            "share_count": _safe_attr(tweet, "retweet_count", 0) or 0,
            "collect_count": _safe_attr(tweet, "bookmark_count", 0) or 0,
            "quote_count": _safe_attr(tweet, "quote_count", 0) or 0,
            "view_count": _safe_attr(tweet, "view_count", 0) or 0,
            "search_keyword": keyword,
            "_sort_time": sort_time,
        }

    def _make_client(self) -> object:
        if self._client_factory is not None:
            return self._client_factory(language=self.language)
        from twikit import Client

        return Client(language=self.language)

    def _dependency_error(self) -> str:
        if importlib.util.find_spec("twikit") is None:
            return (
                "缺少 Twikit；请运行 "
                "python3 -m pip install -r requirements.txt"
            )
        try:
            actual_version = metadata.version("twikit")
        except metadata.PackageNotFoundError:
            return "无法读取 Twikit 安装版本"
        if self.expected_version and actual_version != self.expected_version:
            return (
                "Twikit 版本不匹配："
                f"期望 {self.expected_version}，实际 {actual_version}"
            )
        return ""

    def _cookie_error(self) -> str:
        if not self.cookie_file.is_file():
            return (
                f"Twikit Cookie 文件不存在：{self.cookie_file}；"
                "请先运行 python3 scripts/setup_twikit_session.py"
            )
        try:
            data = json.loads(self.cookie_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"Twikit Cookie 文件无法读取：{exc}"
        if not isinstance(data, dict):
            return "Twikit Cookie 文件必须是 JSON 对象"
        missing = sorted(
            key for key in REQUIRED_COOKIE_KEYS if not str(data.get(key, "")).strip()
        )
        if missing:
            return "Twikit Cookie 缺少必要字段：" + ", ".join(missing)
        return ""

    def _state_error(self) -> str:
        if not self.state_file.exists():
            return ""
        try:
            self._load_seen_ids()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return f"Twikit 状态文件无效：{exc}"
        return ""

    def _load_seen_ids(self) -> List[str]:
        if not self.state_file.exists():
            return []
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("不支持的状态文件格式")
        seen_ids = data.get("seen_ids")
        if not isinstance(seen_ids, list) or any(
            not isinstance(tweet_id, str) for tweet_id in seen_ids
        ):
            raise ValueError("seen_ids 必须是字符串列表")
        return seen_ids
