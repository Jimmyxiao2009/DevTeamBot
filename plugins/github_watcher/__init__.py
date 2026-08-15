"""GitHub 监控插件：装配 GhCli/水位/通知器并在启动时运行轮询任务。

配置错误时不启动轮询（避免用错误目标刷屏），查询命令仍会给出友好错误。
BOT_DISABLE_WATCHER=1 可在测试中禁用轮询。
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress

from nonebot import get_driver, logger

from botcore.config import default_gh_argv, load_settings, validate_settings

from .gh import GhCli
from .notify import Notifier
from .state import WatcherState
from .watcher import Watcher

driver = get_driver()

_watcher: Watcher | None = None
_task: asyncio.Task | None = None

settings = load_settings()
_errors = validate_settings(settings)
if _errors:
    for e in _errors:
        logger.error(f"配置错误（GitHub 轮询未启动）: {e}")
else:
    _gh = GhCli(settings.github_repo, argv=default_gh_argv())
    _state = WatcherState.load(settings.data_dir / "state.json")
    _notifier = Notifier(settings.notify_group_ids, settings.notify_user_ids)
    _watcher = Watcher(
        _gh,
        _state,
        _notifier,
        repo=settings.github_repo,
        nightly_re=settings.nightly_re,
        max_commits_per_poll=settings.notify_max_commits_per_poll,
        poll_interval=float(settings.github_poll_interval),
    )
    logger.info(
        f"GitHub 轮询就绪: {settings.github_repo}，间隔 {settings.github_poll_interval}s，"
        f"通知目标: {len(settings.notify_group_ids)} 群 / {len(settings.notify_user_ids)} 人"
    )


@driver.on_startup
async def _start_watcher() -> None:
    global _task
    if _watcher is None or os.environ.get("BOT_DISABLE_WATCHER") == "1":
        return
    _task = asyncio.create_task(_watcher.run())


@driver.on_shutdown
async def _stop_watcher() -> None:
    if _task is not None:
        _task.cancel()
        with suppress(asyncio.CancelledError):
            await _task
