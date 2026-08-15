"""消息模板与脱敏测试。"""

from __future__ import annotations

from botcore.security import mask_secrets
from plugins.github_watcher.format import format_commit, format_pr, format_release


def test_format_commit_contains_all_fields() -> None:
    msg = format_commit(
        "owner/repo",
        "main",
        {
            "sha": "abc123",
            "message": "fix: 修复崩溃\n\n详细描述",
            "author": "jimmy",
            "url": "https://github.com/owner/repo/commit/abc123",
            "date": "2026-08-15T04:00:00Z",
        },
    )
    assert "新提交 · owner/repo @ main" in msg
    assert "fix: 修复崩溃" in msg
    assert "详细描述" not in msg  # 只取首行
    assert "https://github.com/owner/repo/commit/abc123" in msg


def test_format_release_and_pr() -> None:
    rel = format_release("o/r", {"tag": "v0.3.1", "name": "测试版", "url": "u", "created_at": None, "author": "a"})
    assert "新发布 v0.3.1 · o/r" in rel
    pr = format_pr("o/r", {"number": 42, "title": "t", "user": "u", "base": "main", "url": "u2", "created_at": None})
    assert "新 PR #42 · o/r" in pr
    assert "→ main" in pr


def test_long_title_truncated() -> None:
    from plugins.github_watcher.format import first_line

    assert len(first_line("x" * 200)) <= 60
    assert first_line(None) == "(无标题)"


def test_mask_secrets() -> None:
    text = 'Authorization: Bearer super-secret-token and token="abc123", password=hunter2'
    masked = mask_secrets(text, extra_secrets=["super-secret-token"])
    assert "super-secret-token" not in masked
    assert "hunter2" not in masked
    assert "***" in masked
