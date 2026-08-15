"""通知广播：群 + 私聊。全部目标成功才返回 True（调用方据此推进水位）。

部分失败时返回 False，水位不动，下一轮会对所有目标重发（个别目标可能
收到重复消息——内部工具优先保证不漏发，日志会提示）。
"""

from __future__ import annotations

import nonebot
from nonebot import logger
from nonebot.adapters.onebot.v11 import ActionFailed, Bot, NetworkError


def get_connected_bot() -> Bot | None:
    try:
        bot = nonebot.get_bot()
    except Exception:
        return None
    return bot if isinstance(bot, Bot) else None


class Notifier:
    def __init__(self, group_ids: tuple[int, ...], user_ids: tuple[int, ...]) -> None:
        self.group_ids = group_ids
        self.user_ids = user_ids

    async def _send_group(self, bot: Bot, group_id: int, message: str) -> bool:
        try:
            resp = await bot.send_group_msg(group_id=group_id, message=message)
            ok = resp is not None  # ActionFailed 会抛异常，正常返回即 retcode==0
        except (ActionFailed, NetworkError, TimeoutError) as e:
            logger.warning(f"发送到群 {group_id} 失败: {type(e).__name__}: {e}")
            return False
        return ok

    async def _send_private(self, bot: Bot, user_id: int, message: str) -> bool:
        try:
            resp = await bot.send_private_msg(user_id=user_id, message=message)
            ok = resp is not None
        except (ActionFailed, NetworkError, TimeoutError) as e:
            logger.warning(f"发送到私聊 {user_id} 失败: {type(e).__name__}: {e}")
            return False
        return ok

    async def broadcast(self, message: str) -> bool:
        bot = get_connected_bot()
        if bot is None:
            logger.warning("暂无已连接的 OneBot 客户端（Lagrange 未上线？），本次通知未发送")
            return False
        if not self.group_ids and not self.user_ids:
            # 未配置目标视为成功，避免水位永远卡住
            return True
        results: list[bool] = []
        results.extend(
            await self._send_group(bot, gid, message) for gid in self.group_ids
        )
        results.extend(
            await self._send_private(bot, uid, message) for uid in self.user_ids
        )
        if not all(results):
            logger.warning("本轮通知存在发送失败的目标，水位不推进，下一轮将重试（部分目标可能收到重复消息）")
        return all(results)
