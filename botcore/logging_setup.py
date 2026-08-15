"""loguru（nonebot2 内部日志库）统一配置：脱敏 + 可选文件轮转。"""

from __future__ import annotations

import os
import sys

from loguru import logger

from .config import load_settings
from .security import mask_secrets


def setup_logging() -> None:
    settings = load_settings()
    secrets = [settings.onebot_access_token]

    def _mask(record) -> bool:
        record["message"] = mask_secrets(record["message"], secrets)
        return True

    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        filter=_mask,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        ),
    )
    if settings.log_to_file:
        logger.add(
            "logs/bot.log",
            level=level,
            filter=_mask,
            rotation="10 MB",
            retention=10,
            encoding="utf-8",
            enqueue=True,
        )
