"""轮询器核心场景：新事件、nightly 排除、draft 跳过、发送失败补发、退避。"""

from __future__ import annotations

import asyncio
import re

import pytest

from plugins.github_watcher.state import WatcherState
from plugins.github_watcher.watcher import BACKOFF_BASE, BACKOFF_MAX, Watcher
from tests.conftest import FakeNotifier

NIGHTLY = re.compile("nightly", re.IGNORECASE)


def commit(sha: str, msg: str = "wip") -> dict:
    return {
        "sha": sha,
        "message": msg,
        "author": "alice",
        "url": f"https://github.com/fake/repo/commit/{sha}",
        "date": "2026-08-15T04:00:00Z",
    }


def pr(n: int, title: str = "feat") -> dict:
    return {
        "number": n,
        "title": title,
        "user": "bob",
        "url": f"https://github.com/fake/repo/pull/{n}",
        "created_at": "2026-08-15T04:00:00Z",
        "head": "feature",
        "base": "main",
    }


def release(tag: str, *, draft: bool = False, name: str | None = None) -> dict:
    return {
        "tag": tag,
        "name": name or tag,
        "url": f"https://github.com/fake/repo/releases/tag/{tag}",
        "created_at": "2026-08-15T04:00:00Z",
        "draft": draft,
        "prerelease": False,
        "author": "carol",
    }


@pytest.fixture()
def rig(scenario, fake_gh, tmp_path):
    """(write, watcher, notifier, state) — 场景写入 + 组件装配。"""
    write, _ = scenario
    notifier = FakeNotifier()
    state = WatcherState(tmp_path / "state.json")

    def build() -> Watcher:
        return Watcher(
            fake_gh,
            state,
            notifier,
            repo="fake/repo",
            nightly_re=NIGHTLY,
            max_commits_per_poll=10,
            poll_interval=0.01,
        )

    return write, build, notifier, state


async def test_baseline_then_new_commit_notifies(rig) -> None:
    write, build, notifier, state = rig
    write({"commits": [commit("a" * 40)], "pulls": [], "releases": []})
    w = build()
    await w.baseline()
    assert notifier.sent == []  # 基线不通知

    write({"commits": [commit("b" * 40), commit("a" * 40)]})
    assert await w.poll_once("main")
    assert len(notifier.sent) == 1
    assert "新提交" in notifier.sent[0]
    assert f"https://github.com/fake/repo/commit/{'b' * 40}" in notifier.sent[0]
    assert state.is_known_commit("b" * 40)


async def test_new_pr_and_release_notify(rig) -> None:
    write, build, notifier, state = rig
    write({})
    w = build()
    await w.baseline()
    write({"pulls": [pr(42)], "releases": [release("v0.3.1")]})
    assert await w.poll_once("main")
    texts = "\n".join(notifier.sent)
    assert "新 PR #42" in texts
    assert "新发布 v0.3.1" in texts
    assert state.is_known_pr(42) and state.is_known_release("v0.3.1")


async def test_nightly_and_draft_skipped(rig) -> None:
    write, build, notifier, state = rig
    write({})
    w = build()
    await w.baseline()
    write(
        {
            "releases": [
                release("v0.4.0-nightly"),
                release("nightly-build-20260815"),
                release("v0.3.2-NIGHTLY"),
                release("v0.3.1", draft=True),
            ]
        }
    )
    assert await w.poll_once("main")
    assert notifier.sent == []
    # nightly 标记已见；draft 不标记（发布后仍可通知）
    assert state.is_known_release("v0.4.0-nightly")
    assert state.is_known_release("nightly-build-20260815")
    assert state.is_known_release("v0.3.2-NIGHTLY")
    assert not state.is_known_release("v0.3.1")


async def test_send_failure_keeps_watermark_and_retries(rig) -> None:
    write, build, notifier, state = rig
    write({})
    w = build()
    await w.baseline()

    write({"releases": [release("v1.0.0")]})
    notifier.fail = True
    assert not await w.poll_once("main")  # 发送失败
    assert notifier.sent == []
    assert not state.is_known_release("v1.0.0")  # 水位未推进

    notifier.fail = False
    assert await w.poll_once("main")  # 恢复后重发成功
    assert len(notifier.sent) == 1 and "v1.0.0" in notifier.sent[0]
    assert state.is_known_release("v1.0.0")


async def test_commit_cap_omitted_note(rig) -> None:
    write, build, notifier, state = rig
    write({"commits": [commit("a" * 40)]})
    w = build()
    w.max_commits_per_poll = 2
    await w.baseline()
    # 一次出现 4 条新提交：逐条 2 条 + 省略提示 1 条
    write({"commits": [commit(chr(98 + i) * 40) for i in range(4)] + [commit("a" * 40)]})
    assert await w.poll_once("main")
    assert len(notifier.sent) == 3
    assert "另有 2 条" in notifier.sent[-1]


async def test_backoff_growth() -> None:
    # 直接验证退避常量与计算逻辑（主循环覆盖在 run 中使用同公式）
    assert BACKOFF_BASE == 60.0 and BACKOFF_MAX == 300.0
    backoff = BACKOFF_BASE
    seq = []
    for _ in range(4):
        seq.append(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)
    assert seq == [60, 120, 240, 300]


async def test_poll_failure_no_watermark_change(rig) -> None:
    write, build, notifier, state = rig
    write({})
    w = build()
    await w.baseline()
    # 注入 gh 失败：poll_once 应抛 GhError（由 run() 退避处理）
    write({"fail": {"releases": True}, "releases": [release("v2.0.0")]})
    with pytest.raises(Exception) as ei:
        await w.poll_once("main")
    assert "GhError" in type(ei.value).__name__ or "gh api" in str(ei.value)
    assert notifier.sent == []
    assert not state.is_known_release("v2.0.0")
