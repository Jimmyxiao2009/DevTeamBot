"""gh CLI 封装：子进程调用 + --jq 固定字段解析 + 超时与友好错误。

gh 对数组结果输出 NDJSON（每行一个 JSON 对象），单对象输出一行 JSON，
两种都从 `_parse_output` 统一解析。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from botcore.security import mask_secrets

from nonebot import logger

_AUTH_HINTS = ("not logged in", "bad credentials", "authentication", "gh auth login", "http 401")

COMMITS_JQ = (
    '.[] | {sha: .sha, message: (.commit.message | split("\\n")[0]), '
    "author: (.author.login // .commit.author.name // \"unknown\"), "
    "url: .html_url, date: .commit.author.date}"
)
PRS_JQ = (
    ".[] | {number: .number, title: .title, user: .user.login, "
    "url: .html_url, created_at: .created_at, head: .head.ref, base: .base.ref}"
)
RELEASES_JQ = (
    ".[] | {tag: .tag_name, name: .name, url: .html_url, created_at: .created_at, "
    'draft: .draft, prerelease: .prerelease, author: (.author.login // "unknown")}'
)
REPO_JQ = "{default_branch: .default_branch, full_name: .full_name, html_url: .html_url}"


class GhError(RuntimeError):
    """gh 调用失败；message 面向用户（已脱敏），可直接回复。"""


def _parse_output(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(parsed, dict):
        return [parsed]
    return [item for item in parsed if isinstance(item, dict)]


class GhCli:
    def __init__(
        self,
        repo: str,
        argv: list[str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.repo = repo
        # argv 允许测试注入（如 [python, tests/fake_gh/gh.py]）
        self.argv = list(argv) if argv else ["gh"]
        self.timeout = timeout

    async def _api(self, endpoint: str, jq: str) -> list[dict[str, Any]]:
        args = [*self.argv, "api", endpoint, "--jq", jq]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd(),
            )
        except FileNotFoundError as e:
            raise GhError(
                "未找到 gh 命令，请先安装 GitHub CLI: https://cli.github.com"
            ) from e
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), self.timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise GhError(f"gh api 超时（>{self.timeout:.0f}s）: {endpoint}") from None
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            low = stderr.lower()
            if any(hint in low for hint in _AUTH_HINTS):
                raise GhError("gh 未登录或凭据失效，请在本机运行: gh auth login")
            raise GhError(
                f"gh api 调用失败（退出码 {proc.returncode}）: {mask_secrets(stderr[:300])}"
            )
        return _parse_output(stdout)

    async def repo_info(self) -> dict[str, Any]:
        rows = await self._api(f"repos/{self.repo}", REPO_JQ)
        if not rows:
            raise GhError(f"仓库 {self.repo} 不存在或不可访问")
        return rows[0]

    async def commits(self, per_page: int = 100) -> list[dict[str, Any]]:
        return await self._api(f"repos/{self.repo}/commits?per_page={per_page}", COMMITS_JQ)

    async def open_pulls(self, per_page: int = 30) -> list[dict[str, Any]]:
        return await self._api(
            f"repos/{self.repo}/pulls?state=open&sort=created&direction=desc&per_page={per_page}",
            PRS_JQ,
        )

    async def releases(self, per_page: int = 30) -> list[dict[str, Any]]:
        return await self._api(f"repos/{self.repo}/releases?per_page={per_page}", RELEASES_JQ)
