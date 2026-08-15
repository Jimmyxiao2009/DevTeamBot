"""启动自检：python scripts/check_env.py [--fix]。

检查项：Python 版本、.env 存在与必填项、端口占用、gh 安装与登录。
全部通过返回 0；失败逐项给出中文修复提示。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows GBK 控制台无法编码 ✔✘▲，用 ASCII 安全符号
OK, FAIL, WARN = "[OK]", "[FAIL]", "[WARN]"
issues = 0


def ok(msg: str) -> None:
    print(f"  {OK} {msg}")


def fail(msg: str, fix: str) -> None:
    global issues
    issues += 1
    print(f"  {FAIL} {msg}")
    print(f"      修复: {fix}")


def warn(msg: str) -> None:
    print(f"  {WARN} {msg}")


def check_python() -> None:
    print("[1/5] Python")
    if sys.version_info >= (3, 11):
        ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    else:
        fail(f"当前 {sys.version_info}，需要 3.11+", "安装 Python 3.11 或更高版本")


def check_env_file() -> bool:
    print("[2/5] 配置文件 .env")
    env_path = ROOT / ".env"
    if not env_path.exists():
        example = ROOT / ".env.example"
        if example.exists():
            import shutil

            shutil.copy(example, env_path)
            fail(".env 不存在，已从模板创建，请编辑后重新自检", f"编辑 {env_path}")
        else:
            fail(".env 不存在且找不到模板", "从 .env.example 手动创建 .env")
        return False
    ok(".env 存在")
    return True


def check_config() -> None:
    print("[3/5] 配置项")
    from botcore.config import load_settings, validate_settings

    settings = load_settings()
    errors = validate_settings(settings)
    if errors:
        for e in errors:
            fail(e, "编辑 .env 中对应条目")
    else:
        ok(
            f"token 已设置 / 仓库 {settings.github_repo} / "
            f"{len(settings.notify_group_ids)} 群 + {len(settings.notify_user_ids)} 人 / "
            f"轮询 {settings.github_poll_interval}s"
        )


def check_port() -> None:
    print("[4/5] 端口")
    from botcore.config import load_settings

    settings = load_settings()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex((host, port)) == 0:
            fail(f"{host}:{port} 已被占用", "关闭占用进程，或在 .env 修改 PORT（同步改 Lagrange 配置）")
        else:
            ok(f"{host}:{port} 可用")


def check_gh() -> None:
    print("[5/5] GitHub CLI")
    from botcore.config import default_gh_argv

    argv = default_gh_argv()
    # gh 输出为 UTF-8（含 ✓ 等字符），Windows GBK 环境必须显式指定解码
    run_kw = {"capture_output": True, "timeout": 15, "encoding": "utf-8", "errors": "replace"}
    try:
        ver = subprocess.run([*argv, "--version"], **run_kw)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        gh_hint = "安装 GitHub CLI: https://cli.github.com （private 仓库必须有 gh 且已登录）"
        fail("未找到 gh 命令", gh_hint)
        return
    if ver.returncode != 0:
        fail("gh --version 返回失败", "重新安装 GitHub CLI")
        return
    first_line = (ver.stdout or "").strip().splitlines()[0]
    ok(first_line)
    auth = subprocess.run([*argv, "auth", "status"], **run_kw)
    if auth.returncode != 0 or "Logged in" not in ((auth.stdout or "") + (auth.stderr or "")):
        fail("gh 未登录", "运行: gh auth login（浏览器登录后选 https 协议）")
    else:
        ok("gh 已登录（私有仓库可访问）")


def main() -> int:
    print("== 程序组bot 启动自检 ==\n")
    check_python()
    if check_env_file():
        check_config()
        check_port()
    check_gh()
    print()
    if issues:
        print(f"共 {issues} 个问题需要处理后再次自检。")
        return 1
    print("全部通过。运行 start.bat 或 python bot.py 启动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
