"""水位状态：data/state.json，临时文件 + os.replace 原子写。

单进程 asyncio 内使用，无需加锁。文件损坏时自动备份并从空状态重建
（重建后首轮做基线，不会把历史事件当作新事件刷屏）。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_COMMIT_SHAS = 200
MAX_PR_NUMBERS = 200
MAX_RELEASE_TAGS = 100


def _prune(items: list, cap: int) -> list:
    # 保留最近加入的 cap 个（列表尾部是最新）
    return items[-cap:] if len(items) > cap else items


@dataclass
class WatcherState:
    path: Path
    initialized: bool = False
    known_commit_shas: list[str] = field(default_factory=list)
    known_pr_numbers: list[int] = field(default_factory=list)
    known_release_tags: list[str] = field(default_factory=list)

    # ---- 加载 / 保存 ----
    @classmethod
    def load(cls, path: Path) -> "WatcherState":
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                path=path,
                initialized=bool(raw.get("initialized")),
                known_commit_shas=list(raw.get("known_commit_shas", [])),
                known_pr_numbers=[int(n) for n in raw.get("known_pr_numbers", [])],
                known_release_tags=list(raw.get("known_release_tags", [])),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            backup = path.with_suffix(f".corrupt-{int(time.time())}.bak")
            os.replace(path, backup)
            return cls(path=path)

    def save(self) -> None:
        self.known_commit_shas = _prune(self.known_commit_shas, MAX_COMMIT_SHAS)
        self.known_pr_numbers = _prune(self.known_pr_numbers, MAX_PR_NUMBERS)
        self.known_release_tags = _prune(self.known_release_tags, MAX_RELEASE_TAGS)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "initialized": self.initialized,
            "known_commit_shas": self.known_commit_shas,
            "known_pr_numbers": self.known_pr_numbers,
            "known_release_tags": self.known_release_tags,
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- 提交 ----
    def is_known_commit(self, sha: str) -> bool:
        return sha in self.known_commit_shas

    def mark_commit(self, sha: str) -> None:
        if sha not in self.known_commit_shas:
            self.known_commit_shas.append(sha)

    # ---- PR ----
    def is_known_pr(self, number: int) -> bool:
        return number in self.known_pr_numbers

    def mark_pr(self, number: int) -> None:
        if number not in self.known_pr_numbers:
            self.known_pr_numbers.append(number)

    # ---- Release ----
    def is_known_release(self, tag: str) -> bool:
        return tag in self.known_release_tags

    def mark_release(self, tag: str) -> None:
        if tag not in self.known_release_tags:
            self.known_release_tags.append(tag)
