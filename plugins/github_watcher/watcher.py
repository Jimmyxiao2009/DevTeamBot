"""轮询器：拉取 commits / open pulls / releases，与水位 diff 出新事件并广播。

可靠性约定（与 notify.py 配合）：
- 任何一次发送失败 → 本轮所有水位保持不动，下一轮重发（at-least-once）；
- 轮询失败（gh 错误/超时）→ 指数退避（60s 起，5min 封顶），同样不动水位；
- 首次运行只建立基线（记录现状不通知），避免历史事件刷屏。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from nonebot import logger

from .format import format_commit, format_commit_omitted_note, format_pr, format_release
from .gh import GhCli, GhError
from .notify import Notifier
from .state import WatcherState

BACKOFF_BASE = 60.0
BACKOFF_MAX = 300.0
# 和 query 指令里 file 的上限一致，避免一次刷屏太多文件。
MAX_RELEASE_ATTACHMENTS = 5


def _nightly(tag: str, name: str, pattern) -> bool:
    return bool(pattern.search(tag or "") or pattern.search(name or ""))


class Watcher:
    def __init__(
        self,
        gh: GhCli,
        state: WatcherState,
        notifier: Notifier,
        *,
        repo: str,
        nightly_re,
        max_commits_per_poll: int = 10,
        poll_interval: float = 60.0,
    ) -> None:
        self.gh = gh
        self.state = state
        self.notifier = notifier
        self.repo = repo
        self.nightly_re = nightly_re
        self.max_commits_per_poll = max_commits_per_poll
        self.poll_interval = poll_interval

    # ---- 事件提取（纯函数，便于单测）----
    def _new_commits(self, commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        new = [c for c in commits if not self.state.is_known_commit(str(c.get("sha", "")))]
        return new[: self.max_commits_per_poll]

    def _new_prs(self, pulls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # pulls 最新在前 → 反转为时间正序（旧→新）逐条推送
        return [p for p in pulls if not self.state.is_known_pr(int(p.get("number", 0)))][::-1]

    def _new_releases(self, releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in releases:
            tag = str(r.get("tag", ""))
            if r.get("draft"):
                continue  # 草稿不通知也不标记：正式发布后仍会触发
            if self.state.is_known_release(tag):
                continue
            if _nightly(tag, str(r.get("name") or ""), self.nightly_re):
                self.state.mark_release(tag)  # nightly 静默但标记，避免每轮重复判定
                continue
            out.append(r)
        return out[::-1]  # 时间正序

    # ---- 首轮基线 ----
    async def baseline(self) -> str:
        """记录当前仓库现状为已知，不发通知。返回默认分支名。"""
        info = await self.gh.repo_info()
        branch = str(info.get("default_branch") or "main")
        commits = await self.gh.commits()
        pulls = await self.gh.open_pulls()
        releases = await self.gh.releases()
        for c in commits:
            self.state.mark_commit(str(c.get("sha", "")))
        for p in pulls:
            self.state.mark_pr(int(p.get("number", 0)))
        for r in releases:
            self.state.mark_release(str(r.get("tag", "")))
        self.state.initialized = True
        self.state.save()
        logger.info(
            f"基线完成：{self.repo} @ {branch}"
            f"（提交 {len(commits)} / PR {len(pulls)} / release {len(releases)}），此后开始通知"
        )
        return branch

    # ---- 单轮轮询 ----
    async def poll_once(self, default_branch: str) -> bool:
        """执行一轮检测与通知。返回 False 表示存在发送失败，水位不应保存。"""
        commits = await self.gh.commits()
        pulls = await self.gh.open_pulls()
        releases = await self.gh.releases()

        # 在任何水位标记前统计，供省略提示使用
        total_new_commits = len(
            [c for c in commits if not self.state.is_known_commit(str(c.get("sha", "")))]
        )

        new_commits = self._new_commits(commits)
        new_prs = self._new_prs(pulls)
        new_releases = self._new_releases(releases)

        if not (new_commits or new_prs or new_releases):
            return True  # 无新事件（nightly 标记已写入 state，由 run() 保存）

        all_ok = True

        # 1) releases（时间正序）：文字通知之后，如果这个 release 挂了附件，紧接着
        # 把附件也发过去，跟 query 指令里的 file 是同一份下载/上传逻辑。
        for r in new_releases:
            ok = await self.notifier.broadcast(format_release(self.repo, r))
            if ok and r.get("assets"):
                ok = await self._broadcast_release_files(r) and ok
            all_ok &= ok
            if ok:
                self.state.mark_release(str(r.get("tag", "")))

        # 2) commits（时间正序：旧→新）
        for c in reversed(new_commits):
            ok = await self.notifier.broadcast(format_commit(self.repo, default_branch, c))
            all_ok &= ok
            if ok:
                self.state.mark_commit(str(c.get("sha", "")))
        omitted = total_new_commits - len(new_commits)
        if omitted > 0 and all_ok:
            await self.notifier.broadcast(
                format_commit_omitted_note(self.repo, default_branch, omitted)
            )

        # 3) PRs（时间正序）
        for p in new_prs:
            ok = await self.notifier.broadcast(format_pr(self.repo, p))
            all_ok &= ok
            if ok:
                self.state.mark_pr(int(p.get("number", 0)))

        return all_ok

    # ---- release 附件 ----
    async def _broadcast_release_files(self, r: dict[str, Any]) -> bool:
        """下载新 release 的附件并广播给所有目标。下载失败只影响这一项（文字通知
        已经发出去了），返回 False 让 poll_once 不推进这条 release 的水位，下一轮
        重试；文字通知本身可能因此重发，属于既有的 at-least-once 权衡。"""
        tag = str(r.get("tag", ""))
        try:
            with tempfile.TemporaryDirectory(prefix="release-notify-") as tmp:
                await self.gh.download_release_assets(tag, tmp)
                paths = sorted(str(p) for p in Path(tmp).iterdir() if p.is_file())
                if not paths:
                    return True
                return await self.notifier.broadcast_files(paths[:MAX_RELEASE_ATTACHMENTS])
        except GhError as e:
            logger.warning(f"下载 release {tag} 附件失败，本轮附件未发送: {e}")
            return False

    # ---- 主循环 ----
    async def run(self) -> None:
        backoff = BACKOFF_BASE
        while True:
            try:
                if not self.state.initialized:
                    branch = await self.baseline()
                else:
                    info = await self.gh.repo_info()
                    branch = str(info.get("default_branch") or "main")
                    if await self.poll_once(branch):
                        self.state.save()
                        backoff = BACKOFF_BASE
                    # 发送失败不保存水位：下一轮正常间隔重发
                await asyncio.sleep(self.poll_interval)
            except GhError as e:
                logger.error(f"轮询失败，{backoff:.0f}s 后重试: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            except asyncio.CancelledError:
                logger.info("GitHub 轮询任务已停止")
                raise
            except Exception as e:  # noqa: BLE001 - 主循环兜底，不能让 bot 崩溃
                logger.opt(exception=e).error("轮询循环出现未预期异常")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
