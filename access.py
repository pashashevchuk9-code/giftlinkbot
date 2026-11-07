"""Проверки доступа на серверной стороне.

Каждая команда и каждый callback вызывают эти функции, а не полагаются
на скрытые кнопки. SKAM блокируется раньше любых обычных разрешений.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, User

from config import Settings
from database import Database
from roles import (
    PAYMENT_ADMIN_ROLES,
    Permission,
    Role,
    has_permission,
    is_staff,
    role_from_db,
)

logger = logging.getLogger(__name__)

DENIED_TEXT = "У вас недостаточно прав для выполнения этого действия."
MAINTENANCE_TEXT = (
    "Бот временно находится на техническом обслуживании. Попробуйте позже."
)
BANNED_TEXT = (
    "Ваш аккаунт заблокирован. Обратитесь в поддержку."
)
SKAM_PRIVATE_TEXT = (
    "Аккаунт имеет ограниченный доступ.\n\n"
    "Использование функций бота запрещено. "
    "Доступна только эта информация об ограничении. "
    "Обратитесь в поддержку, если считаете ограничение ошибкой."
)
SKAM_ALERT_TEXT = "Аккаунт имеет ограниченный доступ. Действие недоступно."


def owner_ids(settings: Settings) -> frozenset[int]:
    return frozenset(getattr(settings, "owner_ids", frozenset()) or ())


def env_admin_ids(settings: Settings) -> frozenset[int]:
    return frozenset(getattr(settings, "admin_ids", frozenset()) or ())


def role_of(record: dict[str, Any] | None) -> Role:
    if not record:
        return Role.USER
    return role_from_db(record.get("role"))


def record_name(record: dict[str, Any] | None) -> str:
    if not record:
        return "Пользователь"
    username = record.get("username")
    if username:
        return f"@{username}"
    parts = [record.get("first_name"), record.get("last_name")]
    name = " ".join(str(part) for part in parts if part)
    return name or f"id{record.get('user_id')}"


async def get_actor(db: Database, settings: Settings, user: User) -> dict[str, Any]:
    """Регистрирует пользователя (роль USER) и синхронизирует OWNER."""
    return await db.ensure_user(
        user.id,
        user.username,
        user.first_name,
        user.last_name,
        owner_ids=owner_ids(settings),
    )


async def is_payment_admin(
    db: Database, settings: Settings, user_id: int
) -> bool:
    if user_id in owner_ids(settings) or user_id in env_admin_ids(settings):
        return True
    record = await db.get_user(user_id)
    return role_of(record) in PAYMENT_ADMIN_ROLES


async def can_view_any_deal(
    db: Database, settings: Settings, user_id: int
) -> bool:
    if user_id in owner_ids(settings):
        return True
    record = await db.get_user(user_id)
    return is_staff(role_of(record))


def skam_warning(record: dict[str, Any] | None, user: User | None = None) -> str:
    who = record_name(record)
    if record is None and user is not None and not user.username:
        who = user.first_name or "Пользователь"
    return (
        f"{who} — аккаунт имеет ограниченный доступ. "
        "Будьте осторожны и проверяйте условия сделки."
    )


async def access_block_reason(
    db: Database,
    settings: Settings,
    user_id: int,
    role: Role,
) -> str | None:
    """Причина блокировки обычных действий (SKAM, бан, техрежим)."""
    record = await db.get_user(user_id)
    if role is Role.SKAM:
        return SKAM_PRIVATE_TEXT
    if record and record.get("is_banned"):
        return BANNED_TEXT
    until = record.get("restriction_until") if record else None
    if until and int(until) > 0:
        import time

        if int(until) <= int(time.time()):
            await db.set_restriction(user_id, until=None, reason=None)
        else:
            reason = record.get("restriction_reason") or "Временное ограничение"
            return f"Доступ временно ограничен: {reason}."
    active, _ = await db.maintenance_state()
    if active and not is_staff(role):
        return MAINTENANCE_TEXT
    return None


async def require_message_permission(
    message: Message,
    db: Database,
    settings: Settings,
    permission: Permission,
    *,
    private_only: bool = False,
) -> bool:
    if message.from_user is None:
        return False
    actor = await get_actor(db, settings, message.from_user)
    role = role_of(actor)
    if not has_permission(role, permission):
        await db.log_admin_action(
            message.from_user.id,
            "access_denied",
            details={"permission": permission.value, "role": role.value},
        )
        await message.reply(DENIED_TEXT)
        return False
    if private_only and message.chat.type != ChatType.PRIVATE.value:
        await message.reply(
            "Административные команды выполняются в личном чате с ботом."
        )
        return False
    return True


async def require_callback_permission(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    permission: Permission,
) -> bool:
    actor = await get_actor(db, settings, callback.from_user)
    role = role_of(actor)
    if not has_permission(role, permission):
        await db.log_admin_action(
            callback.from_user.id,
            "access_denied",
            details={"permission": permission.value, "role": role.value},
        )
        await callback.answer(DENIED_TEXT, show_alert=True)
        return False
    return True


def is_command_for_role(role: Role, text: str | None) -> bool:
    """Для техрежима: разрешены только команды, доступные роли."""
    if not text or not text.startswith("/"):
        return False
    from roles import allowed_command_names

    name = text[1:].split(maxsplit=1)[0].split("@", 1)[0].lower()
    return name in allowed_command_names(role)


def maintenance_notice(until: int | None) -> str:
    if until:
        import time
        from datetime import datetime

        left = max(0, int(until) - int(time.time()))
        hours, remainder = divmod(left, 3600)
        minutes = remainder // 60
        finish = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        return (
            f"{MAINTENANCE_TEXT}\n\n"
            f"Ориентировочно до: {finish} (осталось {hours} ч {minutes:02d} мин)."
        )
    return MAINTENANCE_TEXT
