"""通知消息模板：QQ 群纯文本 + GitHub html_url 长链接。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

BRAND = "【程序组bot】"


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def first_line(text: str | None, limit: int = 60) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else "(无标题)"
    return line if len(line) <= limit else line[: limit - 1] + "…"


def format_commit(repo: str, branch: str, c: dict[str, Any]) -> str:
    return (
        f"{BRAND}新提交 · {repo} @ {branch}\n"
        f"{first_line(c.get('message'))} — {c.get('author', 'unknown')}\n"
        f"时间: {_fmt_time(c.get('date'))}\n"
        f"{c.get('url')}"
    )


def format_commit_omitted_note(repo: str, branch: str, omitted: int) -> str:
    return f"{BRAND}新提交 · {repo} @ {branch}\n另有 {omitted} 条更早的新提交未逐条展示，请到仓库查看"

def format_pr(repo: str, p: dict[str, Any]) -> str:
    return (
        f"{BRAND}新 PR #{p.get('number')} · {repo}\n"
        f"{first_line(p.get('title'))} — {p.get('user', 'unknown')} → {p.get('base', '?')}\n"
        f"时间: {_fmt_time(p.get('created_at'))}\n"
        f"{p.get('url')}"
    )


def _format_body(text: str | None, limit: int = 300) -> str:
    body = (text or "").strip()
    if not body:
        return "（无更新说明）"
    return body if len(body) <= limit else body[:limit].rstrip() + "…"


def format_release(repo: str, r: dict[str, Any]) -> str:
    tag = r.get("tag", "")
    name = r.get("name") or tag
    return (
        f"{BRAND}新发布 {tag} · {repo}\n"
        f"{first_line(name)} — {r.get('author', 'unknown')}\n"
        f"此版本的更新内容：\n{_format_body(r.get('body'))}\n"
        f"时间: {_fmt_time(r.get('created_at'))}\n"
        f"{r.get('url')}"
    )
