"""Middleware регистрации пользователей и защиты доступа.

Проверяет SKAM, бан, временные ограничения и технический режим до того,
как сработает любой обработчик. Роль читается из SQLite при каждом событии.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject

from access import (
    BANNED_TEXT,
    MAINTENANCE_TEXT,
    SKAM_ALERT_TEXT,
    SKAM_PRIVATE_TEXT,
    get_actor,
    is_command_for_role,
    maintenance_notice,
    role_of,
    skam_warning,
)
from config import Settings
from database import Database
from roles import Role, is_staff

logger = logging.getLogger(__name__)


def _command_name(text: str | None) -> str | None:
    if not text or not text.startswith("/"):
        return None
    return text[1:].split(maxsplit=1)[0].split("@", 1)[0].lower()


def _looks_like_offer(message: Message) -> bool:
    text = message.text or ""
    lowered = text.lower()
    return (
        "t.me/nft/" in lowered
        or "telegram.me/nft/" in lowered
        or _command_name(text) == "offer"
    )


class AccessGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db: Database | None = data.get("db")
        settings: Settings | None = data.get("settings")
        if db is None or settings is None:
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        if user is None or user.is_bot:
            return await handler(event, data)

        # Оплату нельзя терять из-за техрежима.
        if isinstance(event, Message) and event.successful_payment is not None:
            return await handler(event, data)

        record = await get_actor(db, settings, user)
        role = role_of(record)
        data["actor"] = record
        data["actor_role"] = role

        if role is Role.SKAM:
            await self._block_skam(event, record)
            return None

        if record.get("is_banned"):
            await self._reply_block(event, BANNED_TEXT)
            return None

        until = record.get("restriction_until")
        if until and int(until) > 0:
            import time

            if int(until) <= int(time.time()):
                await db.set_restriction(user.id, until=None, reason=None)
            else:
                reason = record.get("restriction_reason") or "временное ограничение"
                await self._reply_block(
                    event,
                    f"Доступ временно ограничен: {reason}.",
                )
                return None

        active, finish = await db.maintenance_state()
        if active:
            if role is Role.OWNER:
                pass
            elif is_staff(role):
                # Административные команды доступны, обычные действия — нет.
                if isinstance(event, Message) and is_command_for_role(
                    role, event.text
                ):
                    pass
                elif isinstance(event, CallbackQuery) and (
                    event.data or ""
                ).startswith("admin:"):
                    pass
                else:
                    await self._reply_block(event, maintenance_notice(finish))
                    return None
            else:
                await self._reply_block(event, maintenance_notice(finish))
                return None

        return await handler(event, data)

    async def _block_skam(self, event: TelegramObject, record: dict[str, Any]) -> None:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(SKAM_ALERT_TEXT, show_alert=True)
            except Exception:
                pass
            return

        if not isinstance(event, Message):
            return

        if _command_name(event.text) == "start":
            await event.reply(SKAM_PRIVATE_TEXT)
            return

        if event.chat.type in {ChatType.GROUP.value, ChatType.SUPERGROUP.value}:
            if _looks_like_offer(event):
                await event.reply(skam_warning(record, event.from_user))
            return

        await event.reply(SKAM_PRIVATE_TEXT)

    async def _reply_block(self, event: TelegramObject, text: str) -> None:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(text[:200], show_alert=True)
            except Exception:
                pass
            return
        if isinstance(event, Message):
            try:
                await event.reply(text)
            except Exception:
                pass
