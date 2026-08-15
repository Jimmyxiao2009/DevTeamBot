"""脱敏工具：日志与对用户可见的错误信息统一经过这里。"""

from __future__ import annotations

import re
from collections.abc import Iterable

# 形如 token=xxx / "Authorization": "Bearer yyy" / access_token: zzz 的赋值
_SECRET_ASSIGN = re.compile(
    r"(?i)\b(token|secret|password|authorization|access[_-]?token)\b[\"']?\s*[:=]\s*[\"']?([^\"'\s,;&]+)"
)


def mask_secrets(text: str, extra_secrets: Iterable[str] = ()) -> str:
    """把已知秘密值与常见 key=value 形态的秘密替换为 ***。"""
    for secret in extra_secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return _SECRET_ASSIGN.sub(lambda m: f"{m.group(1)}=***", text)
