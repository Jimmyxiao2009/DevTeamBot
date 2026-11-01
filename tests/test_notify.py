"""Notifier.broadcast() / broadcast_files() 直接单测。

broadcast() 部分回归 2026-08-16 的崩溃：`results.extend(await self._send_group(...)
for gid in self.group_ids)` 里生成器表达式一旦包含 await，Python 就把它当成 async
generator（PEP 530），`list.extend()` 消费不了同步以外的迭代器，每次广播都会
抛 `TypeError: 'async_generator' object is not iterable`——bot 日志里连续
崩了 28 轮，没有一条通知真正发出去过。

conftest.py 的 FakeNotifier 整个替换掉了 broadcast()/broadcast_files()，Watcher
层的测试永远走不到这段真实实现，所以这里直接对 Notifier 本体补一份测试。
"""

from __future__ import annotations

from plugins.github_watcher import notify as notify_module
from plugins.github_watcher.notify import Notifier


class _FakeBot:
    """记录被广播到的群/私聊目标，不做真实网络调用。"""

    def __init__(self) -> None:
        self.sent_groups: list[int] = []
        self.sent_users: list[int] = []
        self.uploaded_group_files: list[tuple[int, str, str]] = []
        self.uploaded_private_files: list[tuple[int, str, str]] = []

    async def send_group_msg(self, group_id: int, message: str):
        self.sent_groups.append(group_id)
        return {"status": "ok"}

    async def send_private_msg(self, user_id: int, message: str):
        self.sent_users.append(user_id)
        return {"status": "ok"}

    async def upload_group_file(self, group_id: int, file: str, name: str):
        self.uploaded_group_files.append((group_id, file, name))
        return {"status": "ok"}

    async def upload_private_file(self, user_id: int, file: str, name: str):
        self.uploaded_private_files.append((user_id, file, name))
        return {"status": "ok"}


async def test_broadcast_multiple_groups_and_users_succeeds(monkeypatch) -> None:
    fake_bot = _FakeBot()
    monkeypatch.setattr(notify_module, "get_connected_bot", lambda: fake_bot)

    notifier = Notifier(group_ids=(111, 222), user_ids=(333,))
    ok = await notifier.broadcast("hello")

    assert ok is True
    assert fake_bot.sent_groups == [111, 222]
    assert fake_bot.sent_users == [333]


async def test_broadcast_single_group_only(monkeypatch) -> None:
    # 单个目标也要过一遍：async generator 的类型判定跟元素个数无关，
    # 但保留这个用例用来防止有人"优化"成只测多目标漏掉单目标场景。
    fake_bot = _FakeBot()
    monkeypatch.setattr(notify_module, "get_connected_bot", lambda: fake_bot)

    notifier = Notifier(group_ids=(111,), user_ids=())
    ok = await notifier.broadcast("hello")

    assert ok is True
    assert fake_bot.sent_groups == [111]


async def test_broadcast_no_targets_configured_is_treated_as_success(monkeypatch) -> None:
    fake_bot = _FakeBot()
    monkeypatch.setattr(notify_module, "get_connected_bot", lambda: fake_bot)

    notifier = Notifier(group_ids=(), user_ids=())
    ok = await notifier.broadcast("hello")

    assert ok is True
    assert fake_bot.sent_groups == []
    assert fake_bot.sent_users == []


async def test_broadcast_files_uploads_to_every_group_and_user(monkeypatch, tmp_path) -> None:
    fake_bot = _FakeBot()
    monkeypatch.setattr(notify_module, "get_connected_bot", lambda: fake_bot)

    file_a = tmp_path / "app.zip"
    file_a.write_text("fake binary")
    file_b = tmp_path / "notes.txt"
    file_b.write_text("fake notes")

    notifier = Notifier(group_ids=(111, 222), user_ids=(333,))
    ok = await notifier.broadcast_files([str(file_a), str(file_b)])

    assert ok is True
    assert fake_bot.uploaded_group_files == [
        (111, str(file_a), "app.zip"),
        (222, str(file_a), "app.zip"),
        (111, str(file_b), "notes.txt"),
        (222, str(file_b), "notes.txt"),
    ]
    assert fake_bot.uploaded_private_files == [
        (333, str(file_a), "app.zip"),
        (333, str(file_b), "notes.txt"),
    ]


async def test_broadcast_files_empty_list_is_treated_as_success(monkeypatch) -> None:
    fake_bot = _FakeBot()
    monkeypatch.setattr(notify_module, "get_connected_bot", lambda: fake_bot)

    notifier = Notifier(group_ids=(111,), user_ids=())
    ok = await notifier.broadcast_files([])

    assert ok is True
    assert fake_bot.uploaded_group_files == []
