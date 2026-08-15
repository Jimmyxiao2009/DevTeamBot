"""查询指令的业务逻辑（与 nonebot matcher 解耦，便于单测）。"""

from __future__ import annotations

import time
from typing import Any

from botcore.config import Settings

from ..github_watcher.format import _fmt_time, first_line
from ..github_watcher.gh import GhCli, GhError

DEBOUNCE_SECONDS = 5.0
_last_query: dict[str, float] = {}


def check_debounce(session_key: str) -> bool:
    """同一会话 5 秒内重复查询则忽略（返回 True 表示被防抖拦截）。"""
    now = time.monotonic()
    last = _last_query.get(session_key, 0.0)
    if now - last < DEBOUNCE_SECONDS:
        return True
    _last_query[session_key] = now
    return False


def clamp_count(raw: str | None, default: int = 5, lo: int = 1, hi: int = 10) -> int:
    try:
        n = int((raw or "").strip())
    except ValueError:
        return default
    return max(lo, min(hi, n))


HELP_TEXT = (
    "【程序组bot】指令清单\n"
    "ping — 存活测试\n"
    "release — 最新发布（不含 nightly）\n"
    "commits [n] — 最近 n 条提交（1-10，默认 5）\n"
    "pr — 开放的 PR 列表（最多 10 条）"
)


async def reply_release(gh: GhCli) -> str:
    releases = await gh.releases()
    latest = next((r for r in releases if not r.get("draft")), None)
    if latest is None:
        return "该仓库还没有正式发布（无 release 记录）"
    tag = latest.get("tag", "")
    name = latest.get("name") or tag
    return (
        f"最新发布 {tag}\n{first_line(name)} — {latest.get('author', 'unknown')}\n"
        f"时间: {_fmt_time(latest.get('created_at'))}\n{latest.get('url')}"
    )


async def reply_commits(gh: GhCli, count: int, repo: str) -> str:
    commits = await gh.commits(per_page=min(count, 10))
    if not commits:
        return "没有获取到提交记录"
    lines = [f"最近 {min(count, len(commits))} 条提交 · {repo}"]
    for c in commits[:count]:
        lines.append(f"· {first_line(c.get('message'), 40)} — {c.get('author', '?')} ({c.get('sha', '')[:7]})")
    lines.append(f"https://github.com/{repo}/commits")
    return "\n".join(lines)


async def reply_prs(gh: GhCli, repo: str) -> str:
    pulls = await gh.open_pulls(per_page=10)
    if not pulls:
        return f"当前没有开放的 PR（{repo}）"
    lines = [f"开放的 PR（{len(pulls)} 个）· {repo}"]
    for p in pulls:
        lines.append(f"· #{p.get('number')} {first_line(p.get('title'), 40)} — {p.get('user', '?')}")
    lines.append(f"https://github.com/{repo}/pulls")
    return "\n".join(lines)


async def safe_reply(action, error_hint: str = "查询失败，请稍后再试或联系管理员") -> str:
    """统一兜底：GhError 转成用户可读文本，其余异常记日志并给出通用提示。"""
    from nonebot import logger

    try:
        return await action
    except GhError as e:
        return f"{error_hint}\n原因: {e}"
    except Exception as e:  # noqa: BLE001 - 用户侧只给通用提示，详情进日志
        logger.opt(exception=e).error("查询命令执行异常")
        return error_hint


def build_gh(settings: Settings) -> GhCli:
    from botcore.config import default_gh_argv

    return GhCli(settings.github_repo, argv=default_gh_argv())
