"""集中读取 .env / 环境变量配置。

与 nonebot 自身的 Config 解耦：本模块只依赖 python-dotenv（nonebot2 自带），
方便在测试里注入环境字典。
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_PLACEHOLDER = "请填入你的token"


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key)
    if value is None or value == "":
        return default
    return value


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "")
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _get_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = str(env.get(key, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _get_id_list(env: Mapping[str, str], key: str) -> tuple[list[int], str | None]:
    """解析 NOTIFY_* 配置：JSON 数组或逗号分隔。返回 (ids, 错误信息)。"""
    raw = str(env.get(key, "")).strip()
    if not raw:
        return [], None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            parsed = [parsed]  # 兼容单个裸数字写法：NOTIFY_GROUP_IDS=30000
    except json.JSONDecodeError:
        # 容错：允许 123,456 这种写法
        parsed = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    ids: list[int] = []
    for item in parsed:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            return [], f"{key} 含非数字项: {item!r}"
    return ids, None


@dataclass(frozen=True)
class Settings:
    onebot_access_token: str = ""
    github_repo: str = ""
    github_poll_interval: int = 60
    github_cli_path: str = ""
    notify_group_ids: tuple[int, ...] = ()
    notify_user_ids: tuple[int, ...] = ()
    nightly_exclude_regex: str = "nightly"
    notify_max_commits_per_poll: int = 10
    log_to_file: bool = False
    data_dir: Path = field(default_factory=lambda: Path("data"))

    @property
    def nightly_re(self) -> re.Pattern[str]:
        # 排除规则对 tag 与标题做大小写不敏感匹配
        return re.compile(self.nightly_exclude_regex or "nightly", re.IGNORECASE)

    @property
    def repo_owner(self) -> str:
        parts = self.github_repo.split("/")
        return parts[0] if parts else ""

    @property
    def repo_name(self) -> str:
        parts = self.github_repo.split("/")
        return parts[1] if len(parts) > 1 else ""


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        # 只在缺省时加载 .env；不覆盖已有环境变量
        from dotenv import load_dotenv

        load_dotenv()
        env = os.environ
    groups, _ = _get_id_list(env, "NOTIFY_GROUP_IDS")
    users, _ = _get_id_list(env, "NOTIFY_USER_IDS")
    return Settings(
        onebot_access_token=_get(env, "ONEBOT_ACCESS_TOKEN"),
        github_repo=_get(env, "GITHUB_REPO"),
        github_poll_interval=max(15, _get_int(env, "GITHUB_POLL_INTERVAL", 60)),
        github_cli_path=_get(env, "GITHUB_CLI_PATH"),
        notify_group_ids=tuple(groups),
        notify_user_ids=tuple(users),
        nightly_exclude_regex=_get(env, "NIGHTLY_EXCLUDE_REGEX", "nightly"),
        notify_max_commits_per_poll=max(1, _get_int(env, "NOTIFY_MAX_COMMITS_PER_POLL", 10)),
        log_to_file=_get_bool(env, "LOG_TO_FILE", False),
        data_dir=Path(_get(env, "BOT_DATA_DIR", "data")),
    )


def validate_settings(s: Settings) -> list[str]:
    """返回中文错误列表；为空表示配置可用。"""
    errors: list[str] = []
    if not s.onebot_access_token:
        errors.append("缺少 ONEBOT_ACCESS_TOKEN（在 .env 中填写，与 Lagrange 端 AccessToken 一致）")
    elif s.onebot_access_token == TOKEN_PLACEHOLDER:
        errors.append("ONEBOT_ACCESS_TOKEN 还是模板占位符，请换成真实 token")
    if not s.github_repo or "/" not in s.github_repo or len(s.github_repo.split("/")) != 2:
        errors.append("GITHUB_REPO 需要形如 owner/repo")
    if not s.notify_group_ids and not s.notify_user_ids:
        errors.append("NOTIFY_GROUP_IDS / NOTIFY_USER_IDS 至少配置一个通知目标")
    return errors


def split_cli_path(value: str) -> list[str]:
    parts = shlex.split(value, posix=(os.name != "nt"))
    # Windows 非 posix 模式会保留引号，这里统一去掉成对引号
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]


def default_gh_argv(env: Mapping[str, str] | None = None) -> list[str]:
    """gh 命令前缀：默认 ["gh"]，可用 GITHUB_CLI_PATH 覆盖（支持引号包裹的含空格路径）。"""
    env = os.environ if env is None else env
    raw = str(env.get("GITHUB_CLI_PATH", "")).strip()
    if raw:
        return split_cli_path(raw) or ["gh"]
    return ["gh"]
