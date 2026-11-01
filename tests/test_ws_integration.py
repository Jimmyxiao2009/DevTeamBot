"""端到端集成测试：子进程启动真实 bot（FastAPI + 反向 WS），用伪 Lagrange
WebSocket 客户端验证：
- 错误 bearer token 被拒（403，握手阶段）
- 正确 token 连接成功
- 私聊 ping → pong（API 回包链路）
- 群 @bot ping → pong
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import websockets

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
FAKE_GH = ROOT / "tests" / "fake_gh" / "gh.py"
TOKEN = "it-test-token-abc"
SELF_ID = "10000"
USER_ID = 20000
GROUP_ID = 30000


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ws_connect(url: str, headers: dict[str, str]):
    """兼容 websockets 新旧版本的 header 参数名。"""
    try:
        return websockets.connect(url, additional_headers=headers)
    except TypeError:
        return websockets.connect(url, extra_headers=headers)


@pytest.fixture()
def server(tmp_path):
    port = _free_port()
    env = {
        **os.environ,
        "DRIVER": "~fastapi",
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "LOG_LEVEL": "WARNING",
        "COMMAND_START": '["", "/"]',
        "ONEBOT_ACCESS_TOKEN": TOKEN,
        "GITHUB_REPO": "fake/repo",
        "GITHUB_POLL_INTERVAL": "3600",
        "NOTIFY_GROUP_IDS": str(GROUP_ID),
        "NOTIFY_USER_IDS": str(USER_ID),
        "BOT_DISABLE_WATCHER": "1",
        "BOT_DATA_DIR": str(tmp_path),
        "FAKE_GH_STATE": str(tmp_path / "scenario.json"),
        "GITHUB_CLI_PATH": f'"{VENV_PY}" "{FAKE_GH}"',
    }
    log = tmp_path / "bot.log"
    proc = subprocess.Popen(
        [str(VENV_PY), "bot.py"],
        cwd=ROOT,
        env=env,
        stdout=log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    url = f"ws://127.0.0.1:{port}/onebot/v11/ws"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log_text = log.read_text(encoding="utf-8", errors="replace")
            pytest.fail(f"bot 子进程提前退出:\n{log_text}")
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("bot 服务 20s 内未就绪")
    time.sleep(1.0)  # 等待 FastAPI 路由完全注册
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _recv_api_call(ws, expected: dict, timeout: float = 10.0) -> dict:
    """读取帧直到出现匹配的 API 调用。expected 如 {"action": "send_msg", "message_type": "private"}。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            frame = await asyncio_wait_for(ws.recv(), remaining(deadline))
        except TimeoutError:
            break
        data = json.loads(frame)
        params = data.get("params", {})
        if data.get("action") != expected.get("action"):
            continue
        if "message_type" in expected and params.get("message_type") != expected["message_type"]:
            continue
        return data
    pytest.fail(f"未在 {timeout}s 内收到 API 调用 {expected}")


def remaining(deadline: float) -> float:
    return max(0.1, deadline - time.monotonic())


async def asyncio_wait_for(coro, timeout: float):
    return await __import__("asyncio").wait_for(coro, timeout)


def private_event(text: str) -> str:
    return json.dumps(
        {
            "time": int(time.time()),
            "self_id": int(SELF_ID),
            "post_type": "message",
            "message_type": "private",
            "sub_type": "friend",
            "message_id": 1,
            "user_id": USER_ID,
            "message": text,
            "raw_message": text,
            "font": 0,
            "sender": {"user_id": USER_ID, "nickname": "tester"},
            "to_me": True,
        },
        ensure_ascii=False,
    )


def group_at_event(text: str) -> str:
    raw = f"[CQ:at,qq={SELF_ID}] {text}"
    return json.dumps(
        {
            "time": int(time.time()),
            "self_id": int(SELF_ID),
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": 2,
            "group_id": GROUP_ID,
            "user_id": USER_ID,
            "message": raw,
            "raw_message": raw,
            "font": 0,
            "sender": {"user_id": USER_ID, "nickname": "tester"},
        },
        ensure_ascii=False,
    )


async def test_wrong_token_rejected(server) -> None:
    with pytest.raises(websockets.InvalidHandshake):
        async with _ws_connect(
            server, {"X-Self-ID": SELF_ID, "Authorization": "Bearer wrong-token"}
        ):
            pass


async def test_missing_token_rejected(server) -> None:
    with pytest.raises(websockets.InvalidHandshake):
        async with _ws_connect(server, {"X-Self-ID": SELF_ID}):
            pass


async def test_private_ping_pong(server) -> None:
    async with _ws_connect(
        server, {"X-Self-ID": SELF_ID, "Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        await ws.send(private_event("ping"))
        call = await _recv_api_call(ws, {"action": "send_msg", "message_type": "private"})
        assert call["params"]["user_id"] == USER_ID
        raw = json.dumps(call["params"]["message"], ensure_ascii=False)
        assert "pong" in raw
        await ws.send(
            json.dumps(
                {"status": "ok", "retcode": 0, "data": {"message_id": 9}, "echo": call["echo"]}
            )
        )


async def test_group_at_ping_pong(server) -> None:
    async with _ws_connect(
        server, {"X-Self-ID": SELF_ID, "Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        await ws.send(group_at_event("ping"))
        call = await _recv_api_call(ws, {"action": "send_msg", "message_type": "group"})
        assert call["params"]["group_id"] == GROUP_ID
        raw = json.dumps(call["params"]["message"], ensure_ascii=False)
        assert "pong" in raw
        await ws.send(
            json.dumps(
                {"status": "ok", "retcode": 0, "data": {"message_id": 9}, "echo": call["echo"]}
            )
        )


async def test_group_file_command(server, tmp_path) -> None:
    (tmp_path / "scenario.json").write_text(
        json.dumps(
            {
                "releases": [
                    {
                        "tag": "v1.0.0",
                        "name": "正式版",
                        "url": "https://example.com/r",
                        "created_at": None,
                        "draft": False,
                        "assets": [{"name": "app.zip", "size": 10}],
                    }
                ],
                "release_assets": [{"name": "app.zip", "content": "fake zip bytes"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    async with _ws_connect(
        server, {"X-Self-ID": SELF_ID, "Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        await ws.send(group_at_event("file"))
        upload = await _recv_api_call(ws, {"action": "upload_group_file"})
        assert upload["params"]["group_id"] == GROUP_ID
        assert upload["params"]["name"] == "app.zip"
        await ws.send(json.dumps({"status": "ok", "retcode": 0, "data": {}, "echo": upload["echo"]}))

        summary = await _recv_api_call(ws, {"action": "send_msg", "message_type": "group"})
        raw = json.dumps(summary["params"]["message"], ensure_ascii=False)
        assert "已发送 1 个" in raw
        await ws.send(
            json.dumps(
                {"status": "ok", "retcode": 0, "data": {"message_id": 9}, "echo": summary["echo"]}
            )
        )
