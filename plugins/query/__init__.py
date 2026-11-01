"""查询指令插件：help / ping / release / file / commits / pr。

群聊需 @bot 触发（rule=to_me()），私聊默认视为 to_me 直接发。
防抖：同一会话 5 秒内重复查询静默跳过。
"""

from __future__ import annotations

import os
import tempfile

from nonebot import logger, on_command
from nonebot.adapters.onebot.v11 import ActionFailed, Bot, Message, MessageEvent, NetworkError
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from botcore.config import load_settings, validate_settings

from ..github_watcher.gh import GhCli, GhError
from .replies import (
    HELP_TEXT,
    MAX_FILE_ATTACHMENTS,
    build_gh,
    check_debounce,
    clamp_count,
    download_release_files,
    latest_release,
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
file_cmd = on_command("file", aliases={"文件"}, rule=_RULE, priority=10, block=True)
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


async def _send_release_files(bot: Bot, event: MessageEvent, gh: GhCli) -> str:
    """下载最新 release 的附件并发到当前会话，返回汇总文本；异常一律兜底成友好提示。"""
    try:
        release = await latest_release(gh)
        if release is None:
            return "该仓库还没有正式发布（无 release 记录）"
        tag = release.get("tag", "")
        if not release.get("assets"):
            return f"最新发布 {tag} 没有附加文件（只有源码包）\n{release.get('url')}"

        group_id = getattr(event, "group_id", None)
        with tempfile.TemporaryDirectory(prefix="napcat-release-") as tmp:
            paths = await download_release_files(gh, release, tmp)
            if not paths:
                return f"最新发布 {tag} 的附件下载失败或为空\n{release.get('url')}"
            sent = 0
            for path in paths[:MAX_FILE_ATTACHMENTS]:
                name = os.path.basename(path)
                try:
                    if group_id is not None:
                        await bot.upload_group_file(group_id=group_id, file=path, name=name)
                    else:
                        await bot.upload_private_file(user_id=event.user_id, file=path, name=name)
                    sent += 1
                except (ActionFailed, NetworkError, TimeoutError) as e:
                    logger.warning(f"发送文件 {name} 失败: {type(e).__name__}: {e}")

        omitted = len(paths) - min(len(paths), MAX_FILE_ATTACHMENTS)
        lines = [f"最新发布 {tag} 共 {len(paths)} 个附件，已发送 {sent} 个"]
        if omitted:
            lines.append(f"另有 {omitted} 个未发送，请到 {release.get('url')} 下载")
        return "\n".join(lines)
    except GhError as e:
        return f"查询/下载发布文件失败\n原因: {e}"
    except Exception as e:  # noqa: BLE001 - 用户侧只给通用提示，详情进日志
        logger.opt(exception=e).error("file 指令执行异常")
        return "查询失败，请稍后再试或联系管理员"


@file_cmd.handle()
async def _file(matcher: Matcher, event: MessageEvent, bot: Bot) -> None:
    if check_debounce(_session_key(event)):
        matcher.skip()
    if _cfg_errors:
        await matcher.finish(_UNAVAILABLE)
    await matcher.finish(await _send_release_files(bot, event, build_gh(settings)))


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
