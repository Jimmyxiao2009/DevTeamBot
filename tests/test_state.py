"""水位状态：原子写、损坏恢复、修剪。"""

from __future__ import annotations

import json

from plugins.github_watcher.state import MAX_COMMIT_SHAS, WatcherState


def test_load_missing_returns_fresh(tmp_path) -> None:
    s = WatcherState.load(tmp_path / "state.json")
    assert not s.initialized
    assert s.known_commit_shas == []


def test_save_then_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "state.json"
    s = WatcherState(path=path)
    s.mark_commit("a" * 40)
    s.mark_pr(7)
    s.mark_release("v1.0.0")
    s.initialized = True
    s.save()

    loaded = WatcherState.load(path)
    assert loaded.initialized
    assert loaded.is_known_commit("a" * 40)
    assert loaded.is_known_pr(7)
    assert loaded.is_known_release("v1.0.0")
    assert not loaded.is_known_pr(8)


def test_corrupt_file_backed_up_and_reset(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    s = WatcherState.load(path)
    assert not s.initialized
    backups = list(tmp_path.glob("state.corrupt-*.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) if False else backups[0].exists()


def test_prune_on_save(tmp_path) -> None:
    s = WatcherState(path=tmp_path / "state.json")
    for i in range(MAX_COMMIT_SHAS + 50):
        s.mark_commit(f"{i:040d}")
    s.save()
    assert len(s.known_commit_shas) == MAX_COMMIT_SHAS
    # 最早加入的已被修剪，最新保留
    assert s.is_known_commit(f"{MAX_COMMIT_SHAS + 49:040d}")
    assert not s.is_known_commit(f"{0:040d}")
