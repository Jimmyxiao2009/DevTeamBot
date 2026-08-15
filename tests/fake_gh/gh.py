"""Fake gh CLI：用法 `gh.py api <endpoint> --jq <expr>`（--jq 被忽略）。

场景 JSON 由环境变量 FAKE_GH_STATE 指定，字段为 jq 投影后的形状：
{
  "repo":    {...} 或缺省（用默认）,
  "commits": [...]  / "pulls": [...]  / "releases": [...],
  "fail": {"commits": true, "auth": true}   # 可选失败注入
}
测试在两轮轮询之间改写场景文件即可模拟"新事件出现"。
"""

from __future__ import annotations

import json
import os
import sys

DEFAULT_REPO = {
    "default_branch": "main",
    "full_name": "fake/repo",
    "html_url": "https://github.com/fake/repo",
}


def _load() -> dict:
    path = os.environ.get("FAKE_GH_STATE")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _endpoint_key(endpoint: str) -> str:
    if "/commits" in endpoint:
        return "commits"
    if "/pulls" in endpoint:
        return "pulls"
    if "/releases" in endpoint:
        return "releases"
    return "repo"


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "--version":
        print("gh version 2.92.0 (fake)")
        return 0
    scenario = _load()
    if args[:2] == ["auth", "status"]:
        if scenario.get("fail", {}).get("auth"):
            print("gh auth login required", file=sys.stderr)
            return 1
        print("✓ Logged in to github.com account fake (keyring)")
        return 0
    if args[0] != "api":
        print(f"fake gh: unsupported args {args}", file=sys.stderr)
        return 2

    key = _endpoint_key(args[1] if len(args) > 1 else "")
    if scenario.get("fail", {}).get(key):
        print(f"fake gh: injected failure for {key}", file=sys.stderr)
        return 1

    rows = scenario.get(key)
    if rows is None:
        if key == "repo":
            print(json.dumps(DEFAULT_REPO, ensure_ascii=False))
            return 0
        return 0  # 列表为空：输出空
    if isinstance(rows, dict):
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
