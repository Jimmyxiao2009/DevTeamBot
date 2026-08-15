"""配置解析与校验测试。"""

from __future__ import annotations

from botcore.config import Settings, default_gh_argv, load_settings, split_cli_path, validate_settings

VALID = {
    "ONEBOT_ACCESS_TOKEN": "tok-123",
    "GITHUB_REPO": "owner/repo",
    "NOTIFY_GROUP_IDS": '["123", 456]',
    "NOTIFY_USER_IDS": "10001,10002",
}


def test_valid_settings() -> None:
    s = load_settings(VALID)
    assert s.github_repo == "owner/repo"
    assert s.notify_group_ids == (123, 456)
    assert s.notify_user_ids == (10001, 10002)
    assert validate_settings(s) == []


def test_missing_everything() -> None:
    errors = validate_settings(Settings())
    assert len(errors) == 3  # token / repo / 目标


def test_placeholder_token_rejected() -> None:
    env = {**VALID, "ONEBOT_ACCESS_TOKEN": "请填入你的token"}
    assert any("占位符" in e for e in validate_settings(load_settings(env)))


def test_bad_repo_format() -> None:
    env = {**VALID, "GITHUB_REPO": "justname"}
    assert any("owner/repo" in e for e in validate_settings(load_settings(env)))


def test_defaults_and_clamps() -> None:
    s = load_settings({**VALID, "GITHUB_POLL_INTERVAL": "5", "NOTIFY_MAX_COMMITS_PER_POLL": "0"})
    assert s.github_poll_interval == 15  # 下限保护
    assert s.notify_max_commits_per_poll == 1
    assert s.nightly_re.search("Nightly-Build")


def test_cli_path_split() -> None:
    assert split_cli_path('"C:/Program Files/gh/bin/gh.exe"') == ["C:/Program Files/gh/bin/gh.exe"]
    assert default_gh_argv({}) == ["gh"]
    assert default_gh_argv({"GITHUB_CLI_PATH": "python fake_gh.py"}) == ["python", "fake_gh.py"]
