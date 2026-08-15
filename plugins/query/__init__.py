"""查询指令插件：help / ping / release / commits / pr。

群聊需 @bot 触发（rule=to_me()），私聊默认视为 to_me 直接发。
防抖：同一会话 5 秒内重复查询静默跳过。
"""

from __future__ import annotations

from nonebot import logger, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from botcore.config import load_settings, validate_settings

from .replies import (
    HELP_TEXT,
    build_gh,
    check_debounce,
    clamp_count,
    reply_commits,
    reply_prs,
    reply_release,
    safe_reply,
)

settings = load_settings()
_cfg_errors = validate_settings(settings)
if _cfg_errors:
    logger.warning(f"查询指令配置不完整，指令将返回提示: {'；'.join(_cfg_errors)}")

_RULE = to_me()
_UNAVAILABLE = "bot 配置未完成，暂时无法查询。请管理员检查 .env（GITHUB_REPO / 通知目标等）"


def _session_key(event: MessageEvent) -> str:
    return f"{getattr(event, 'session_type', '?')}:{getattr(event, 'session_id', '')}"


help_cmd = on_command("help", aliases={"帮助"}, rule=_RULE, priority=10, block=True)
ping_cmd = on_command("ping", rule=_RULE, priority=5, block=True)
release_cmd = on_command("release", aliases={"发布"}, rule=_RULE, priority=10, block=True)
commits_cmd = on_command("commits", aliases={"提交"}, rule=_RULE, priority=10, block=True)
pr_cmd = on_command("pr", rule=_RULE, priority=10, block=True)


@help_cmd.handle()
async def _help(matcher: Matcher) -> None:
    await matcher.finish(HELP_TEXT if not _cfg_errors else f"{HELP_TEXT}\n\n⚠ {_UNAVAILABLE}")


@ping_cmd.handle()
async def _ping(matcher: Matcher) -> None:
    await matcher.finish("pong")


@release_cmd.handle()
async def _release(matcher: Matcher, event: MessageEvent) -> None:
    if check_debounce(_session_key(event)):
        matcher.skip()
    if _cfg_errors:
        await matcher.finish(_UNAVAILABLE)
    await matcher.finish(await safe_reply(reply_release(build_gh(settings)), "查询最新发布失败"))


@commits_cmd.handle()
async def _commits(matcher: Matcher, event: MessageEvent, args: Message = CommandArg()) -> None:
    if check_debounce(_session_key(event)):
        matcher.skip()
    if _cfg_errors:
        await matcher.finish(_UNAVAILABLE)
    count = clamp_count(str(args.extract_plain_text()))
    await matcher.finish(
        await safe_reply(reply_commits(build_gh(settings), count, settings.github_repo), "查询提交失败")
    )


@pr_cmd.handle()
async def _pr(matcher: Matcher, event: MessageEvent) -> None:
    if check_debounce(_session_key(event)):
        matcher.skip()
    if _cfg_errors:
        await matcher.finish(_UNAVAILABLE)
    await matcher.finish(await safe_reply(reply_prs(build_gh(settings), settings.github_repo), "查询 PR 失败"))
