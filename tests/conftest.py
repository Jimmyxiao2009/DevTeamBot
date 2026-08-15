"""共享夹具：fake gh 的 GhCli 构造与场景文件工具。

插件包在 import 时会调用 nonebot.get_driver()（nonebot 插件惯例），
因此单测进程先初始化一个最小 nonebot（仅注册，不启动服务，
on_startup 钩子不会触发，轮询任务不会运行）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DRIVER", "~fastapi")
os.environ.setdefault("BOT_DISABLE_WATCHER", "1")
os.environ.setdefault("ONEBOT_ACCESS_TOKEN", "test-token")
os.environ.setdefault("GITHUB_REPO", "fake/repo")

import nonebot  # noqa: E402

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from plugins.github_watcher.gh import GhCli  # noqa: E402

FAKE_GH = ROOT / "tests" / "fake_gh" / "gh.py"


class FakeNotifier:
    """记录发送内容；fail=True 时全部失败（模拟断线）。"""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    async def broadcast(self, message: str) -> bool:
        if self.fail:
            return False
        self.sent.append(message)
        return True


@pytest.fixture()
def scenario(tmp_path, monkeypatch):
    """返回 (write, path)：写入场景 JSON 并指向 FAKE_GH_STATE。"""
    path = tmp_path / "scenario.json"
    monkeypatch.setenv("FAKE_GH_STATE", str(path))

    def write(data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return write, path


@pytest.fixture()
def fake_gh(tmp_path, monkeypatch):
    """注入 fake gh 的 GhCli；同时隔离真实 GITHUB_CLI_PATH。"""
    monkeypatch.delenv("GITHUB_CLI_PATH", raising=False)
    return GhCli("fake/repo", argv=[sys.executable, str(FAKE_GH)])
