"""查询指令业务逻辑：参数钳制、防抖、各类回复与错误兜底。"""

from __future__ import annotations

import pytest

from plugins.query.replies import (
    HELP_TEXT,
    check_debounce,
    clamp_count,
    reply_commits,
    reply_prs,
    reply_release,
    safe_reply,
)


def test_clamp_count() -> None:
    assert clamp_count(None) == 5
    assert clamp_count("") == 5
    assert clamp_count("abc") == 5
    assert clamp_count("0") == 1
    assert clamp_count("3") == 3
    assert clamp_count("99") == 10


def test_debounce(monkeypatch) -> None:
    clock = {"t": 1000.0}  # 非零起点，避免与默认 last=0.0 撞车误判
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])
    assert not check_debounce("s")  # 首次放行
    assert check_debounce("s")  # 5 秒内拦截
    clock["t"] += 6
    assert not check_debounce("s")  # 窗口过后放行
    assert not check_debounce("other")  # 不同会话互不影响


async def test_reply_release_no_data(fake_gh, scenario) -> None:
    write, _ = scenario
    write({"releases": []})
    assert "没有" in await reply_release(fake_gh)


async def test_reply_release_skips_draft(fake_gh, scenario) -> None:
    write, _ = scenario
    write(
        {
            "releases": [
                {"tag": "v9.0.0", "name": "draft one", "url": "u1", "created_at": None, "draft": True, "author": "x"},
                {"tag": "v0.9.0", "name": "正式版", "url": "u2", "created_at": None, "draft": False, "author": "y"},
            ]
        }
    )
    text = await reply_release(fake_gh)
    assert "v0.9.0" in text and "v9.0.0" not in text


async def test_reply_commits(fake_gh, scenario) -> None:
    write, _ = scenario
    write(
        {
            "commits": [
                {"sha": "aaaaaaa", "message": "first line\nbody", "author": "a", "url": "u", "date": None},
                {"sha": "bbbbbbb", "message": "second", "author": "b", "url": "u", "date": None},
            ]
        }
    )
    text = await reply_commits(fake_gh, 5, "fake/repo")
    assert "first line" in text and "body" not in text
    assert "aaaaaaa" in text
    assert "https://github.com/fake/repo/commits" in text


async def test_reply_prs_empty(fake_gh, scenario) -> None:
    write, _ = scenario
    write({"pulls": []})
    assert "没有开放的 PR" in await reply_prs(fake_gh, "fake/repo")


async def test_safe_reply_wraps_gh_error(fake_gh, scenario) -> None:
    write, _ = scenario
    write({"fail": {"commits": True}})

    async def action() -> str:
        return await reply_commits(fake_gh, 5, "fake/repo")

    text = await safe_reply(action(), "查询提交失败")
    assert text.startswith("查询提交失败")


def test_help_text_lists_commands() -> None:
    for cmd in ("ping", "release", "commits", "pr"):
        assert cmd in HELP_TEXT
