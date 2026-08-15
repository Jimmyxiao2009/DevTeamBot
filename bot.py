"""bot 入口：python bot.py。

加载顺序：日志脱敏 → nonebot 初始化（.env）→ 注册 OneBot v11 适配器
→ 加载插件（github_watcher / query）→ 启动 FastAPI（反向 WS 端点
/onebot/v11/ws 由适配器自动注册，Lagrange 作为 WS 客户端连入）。
"""

from __future__ import annotations

import os

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from botcore.logging_setup import setup_logging

setup_logging()

# BOT_ENV_FILE 仅用于测试注入临时 .env；缺省时 nonebot 读取工作区根目录的 .env
_env_file = os.environ.get("BOT_ENV_FILE")
nonebot.init(**({"_env_file": _env_file} if _env_file else {}))
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()
