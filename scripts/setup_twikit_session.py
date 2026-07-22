"""交互式创建仅保存在本机的 Twikit Cookie 文件（实验功能）。"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402


KNOWN_TRANSACTION_ERROR = "Couldn't get KEY_BYTE indices"
KNOWN_TRANSACTION_ISSUE_URL = "https://github.com/d60/twikit/issues/409"


def _cookie_path() -> Path:
    path = Path(config.TWIKIT_COOKIE_FILE).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


async def create_session(path: Path) -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "Twikit 2.3.3 实际运行需要 Python >=3.10；"
            f"当前为 {sys.version_info.major}.{sys.version_info.minor}"
        )
    try:
        from twikit import Client
    except ImportError as exc:
        raise RuntimeError(
            "缺少 Twikit，请先运行 python3 -m pip install -r requirements.txt"
        ) from exc

    username = input("X 用户名（不含 @）：").strip()
    secondary = input("X 邮箱或手机号（可留空）：").strip()
    password = getpass.getpass("X 密码（不会显示或保存）：")
    if not username or not password:
        raise ValueError("用户名和密码不能为空")

    path.parent.mkdir(parents=True, exist_ok=True)
    client = Client(language=config.TWIKIT_LANGUAGE)
    try:
        await client.login(
            auth_info_1=username,
            auth_info_2=secondary or None,
            password=password,
            cookies_file=str(path),
        )
    finally:
        await client.http.aclose()

    if not path.is_file():
        raise RuntimeError("Twikit 登录完成后没有生成 Cookie 文件")
    if os.name != "nt":
        path.chmod(0o600)


def _format_login_error(exc: Exception) -> str:
    if KNOWN_TRANSACTION_ERROR in str(exc):
        return (
            "登录失败：Twikit 2.3.3 当前无法解析 X 网页请求所需的交易参数\n"
            f"已知错误：{KNOWN_TRANSACTION_ERROR}\n"
            "这通常发生在校验用户名和密码之前，不代表凭证填写错误。"
            "请停止重复登录。\n"
            f"上游问题：{KNOWN_TRANSACTION_ISSUE_URL}"
        )
    return f"登录失败：{type(exc).__name__}: {exc}"


def main() -> int:
    path = _cookie_path()
    if path.exists():
        print(f"Cookie 文件已存在：{path}")
        print("如需重新登录，请先手动移走该文件，再重新运行本脚本。")
        return 2

    print("该操作只在本机保存登录 Cookie，不会保存密码。")
    print(f"Cookie 路径：{path}")
    try:
        asyncio.run(create_session(path))
    except (KeyboardInterrupt, EOFError):
        print("\n已取消登录")
        return 130
    except Exception as exc:
        print(_format_login_error(exc))
        return 1

    print("Twikit 本地会话已创建。请勿提交或分享该文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
