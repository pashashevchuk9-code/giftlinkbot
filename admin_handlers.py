"""Административные команды и управление ролями.

Все команды проверяют роль заново на сервере через БД и пишут
административные действия в журнал admin_log.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from access import (
    DENIED_TEXT,
    env_admin_ids,
    get_actor,
    owner_ids,
    require_message_permission,
    role_of,
)
from config import Settings
from constants import OfferStatus, status_label
from database import Database
from roles import (
    ALL_ROLES,
    DEAL_VIEWER_ROLES,
    Permission,
    Role,
    STAFF_ROLES,
    parse_role,
    role_label,
)

logger = logging.getLogger(__name__)
router = Router(name="admin")

_ACTIVE_STATUSES: tuple[str, ...] = (
    OfferStatus.PENDING.value,
    OfferStatus.ACCEPTED.value,
    OfferStatus.AWAITING_PAYMENT.value,
    OfferStatus.PAID.value,
    OfferStatus.TRANSFERRING.value,
    OfferStatus.NFT_TRANSFERRED.value,
    OfferStatus.PAYOUT_PENDING.value,
    OfferStatus.DISPUTED.value,
)

_MAX_RESTRICTION_HOURS = 24 * 30


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _short(value: str, limit: int = 40) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _user_label(record: dict[str, Any]) -> str:
    username = record.get("username")
    if username:
        return f"@{_esc(username)}"
    name = " ".join(
        str(part)
        for part in (record.get("first_name"), record.get("last_name"))
        if part
    )
    return f"{_esc(name)} (<code>{record['user_id']}</code>)" if name else (
        f"<code>{record['user_id']}</code>"
    )


async def _guard(
    message: Message,
    db: Database,
    settings: Settings,
    permission: Permission,
) -> dict[str, Any] | None:
    if message.from_user is None:
        return None
    if not await require_message_permission(
        message, db, settings, permission, private_only=True
    ):
        return None
    return await get_actor(db, settings, message.from_user)


async def _guard_actor(
    message: Message,
    db: Database,
    settings: Settings,
    permission: Permission,
) -> tuple[dict[str, Any] | None, Role]:
    actor = await _guard(message, db, settings, permission)
    if actor is None:
        return None, Role.USER
    return actor, role_of(actor)


async def _resolve_target(
    db: Database,
    settings: Settings,
    message: Message,
    raw: str | None,
) -> dict[str, Any] | None:
    user_id: int | None = None
    username: str | None = None

    if raw:
        value = raw.strip()
        if value.isdigit():
            user_id = int(value)
        elif value.startswith("@"):
            username = value
        else:
            username = f"@{value}"
    elif message.reply_to_message and message.reply_to_message.from_user:
        reply_user = message.reply_to_message.from_user
        user_id = reply_user.id
        username = reply_user.username
    else:
        return None

    if user_id is not None:
        record = await db.get_user(user_id)
        if record is None:
            record = await db.ensure_user(
                user_id,
                username.lstrip("@") if username else None,
                None,
                None,
                owner_ids=owner_ids(settings),
            )
        return record

    if username:
        record = await db.get_user_by_username(username)
        return record
    return None


def _cannot_manage(actor_role: Role, target_role: Role) -> str | None:
    if target_role is Role.OWNER:
        return "Нельзя изменять владельца бота (OWNER)."
    if actor_role is not Role.OWNER and target_role in STAFF_ROLES:
        return "Управлять администраторами может только OWNER."
    return None


def _target_error() -> str:
    return (
        "Пользователь не найден. Укажите Telegram ID, @username или ответьте "
        "на его сообщение. Пользователь должен хотя бы раз написать боту."
    )


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramAPIError:
        pass


# ------------------------------------------------------------------ TECH ADMIN


@router.message(Command("userinfo"))
async def cmd_userinfo(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_USERS):
        return
    parts = (message.text or "").split(maxsplit=1)
    target = await _resolve_target(
        db, settings, message, parts[1] if len(parts) > 1 else None
    )
    if target is None:
        await message.reply(_target_error())
        return
    warnings = await db.count_warnings(target["user_id"])
    completed = await db.count_completed_deals(target["user_id"])
    registered = (
        datetime.fromtimestamp(
            int(target["registered_at"]), tz=settings.tz
        ).strftime("%d.%m.%Y %H:%M")
        if target.get("registered_at")
        else "—"
    )
    lines = [
        "<b>Информация о пользователе</b>",
        "",
        f"ID: <code>{target['user_id']}</code>",
        f"Username: {_user_label(target)}",
        f"Роль: <b>{role_label(role_of(target))}</b>",
        f"Регистрация: {registered}",
        f"Завершённые сделки: <b>{completed}</b>",
        f"Предупреждения: <b>{warnings}</b>",
        f"Бан: {'да' if target.get('is_banned') else 'нет'}",
    ]
    if target.get("is_banned") and target.get("ban_reason"):
        lines.append(f"Причина бана: {_esc(target['ban_reason'])}")
    until = target.get("restriction_until")
    if until and int(until) > int(time.time()):
        finish = datetime.fromtimestamp(
            int(until), tz=settings.tz
        ).strftime("%d.%m.%Y %H:%M")
        lines.append(f"Ограничение до: {finish}")
        if target.get("restriction_reason"):
            lines.append(f"Причина: {_esc(target['restriction_reason'])}")
    await message.reply("\n".join(lines))


@router.message(Command("ban"))
async def cmd_ban(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    actor, actor_role = await _guard_actor(
        message, db, settings, Permission.BAN_USERS
    )
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=2)
    target = await _resolve_target(
        db, settings, message, parts[1] if len(parts) > 1 else None
    )
    if target is None:
        await message.reply(_target_error())
        return
    target_role = role_of(target)
    if target["user_id"] == actor["user_id"]:
        await message.reply("Нельзя заблокировать себя.")
        return
    reason = _cannot_manage(actor_role, target_role)
    if reason:
        await message.reply(reason)
        return
    ban_reason = parts[2].strip() if len(parts) > 2 else "Нарушение правил"
    await db.set_ban(
        target["user_id"],
        banned=True,
        admin_id=actor["user_id"],
        reason=ban_reason,
    )
    await db.log_admin_action(
        actor["user_id"],
        "ban",
        target["user_id"],
        {"reason": ban_reason},
    )
    await _notify(
        bot,
        target["user_id"],
        f"Ваш аккаунт заблокирован.\nПричина: {ban_reason}",
    )
    await message.reply(
        f"Пользователь {_user_label(target)} заблокирован.\n"
        f"Причина: {_esc(ban_reason)}"
    )


@router.message(Command("unban"))
async def cmd_unban(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    actor, actor_role = await _guard_actor(
        message, db, settings, Permission.BAN_USERS
    )
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    target = await _resolve_target(
        db, settings, message, parts[1] if len(parts) > 1 else None
    )
    if target is None:
        await message.reply(_target_error())
        return
    reason = _cannot_manage(actor_role, role_of(target))
    if reason:
        await message.reply(reason)
        return
    await db.set_ban(
        target["user_id"],
        banned=False,
        admin_id=actor["user_id"],
    )
    await db.log_admin_action(
        actor["user_id"], "unban", target["user_id"]
    )
    await _notify(
        bot,
        target["user_id"],
        "Ваш аккаунт разблокирован. Доступ к боту восстановлен.",
    )
    await message.reply(f"Пользователь {_user_label(target)} разблокирован.")


@router.message(Command("warnings"))
async def cmd_warnings(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(
        message, db, settings, Permission.MANAGE_RESTRICTIONS
    ):
        return
    parts = (message.text or "").split(maxsplit=1)
    target = await _resolve_target(
        db, settings, message, parts[1] if len(parts) > 1 else None
    )
    if target is None:
        await message.reply(_target_error())
        return
    warnings = await db.list_warnings(target["user_id"], limit=10)
    lines = [
        f"<b>Предупреждения {_user_label(target)}</b>",
        f"Всего: <b>{await db.count_warnings(target['user_id'])}</b>",
    ]
    if not warnings:
        lines.append("\nПредупреждений нет.")
    for item in warnings:
        created = datetime.fromtimestamp(
            int(item["created_at"]), tz=settings.tz
        ).strftime("%d.%m.%Y %H:%M")
        lines.append(
            f"{created} · {_esc(item.get('reason') or 'без причины')} "
            f"(<code>{item['admin_id']}</code>)"
        )
    until = target.get("restriction_until")
    if until and int(until) > int(time.time()):
        finish = datetime.fromtimestamp(
            int(until), tz=settings.tz
        ).strftime("%d.%m.%Y %H:%M")
        lines.append(f"\nВременное ограничение до: {finish}")
    await message.reply("\n".join(lines))


@router.message(Command("warn"))
async def cmd_warn(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    actor, actor_role = await _guard_actor(
        message, db, settings, Permission.MANAGE_RESTRICTIONS
    )
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 2:
        await message.reply(
            "Использование: <code>/warn ID_ИЛИ_@username [часы] причина</code>"
        )
        return
    target = await _resolve_target(db, settings, message, parts[1])
    if target is None:
        await message.reply(_target_error())
        return
    reason_text = _cannot_manage(actor_role, role_of(target))
    if reason_text:
        await message.reply(reason_text)
        return
    if target["user_id"] == actor["user_id"]:
        await message.reply("Нельзя выдать предупреждение себе.")
        return

    hours = 0
    reason_parts: list[str] = []
    if len(parts) > 2:
        if parts[2].isdigit():
            hours = int(parts[2])
            if len(parts) > 3:
                reason_parts.append(parts[3])
        else:
            reason_parts.append(" ".join(parts[2:]))
    reason = " ".join(reason_parts).strip() or "Нарушение правил"
    if hours > _MAX_RESTRICTION_HOURS:
        await message.reply(
            f"Максимальное временное ограничение — {_MAX_RESTRICTION_HOURS} ч."
        )
        return

    await db.add_warning(target["user_id"], actor["user_id"], reason)
    if hours > 0:
        until = int(time.time()) + hours * 3600
        await db.set_restriction(
            target["user_id"], until=until, reason=reason
        )
    await db.log_admin_action(
        actor["user_id"],
        "warn",
        target["user_id"],
        {"reason": reason, "hours": hours},
    )
    if hours > 0:
        await _notify(
            bot,
            target["user_id"],
            f"Выдано предупреждение и временное ограничение на {hours} ч.\n"
            f"Причина: {reason}",
        )
        await message.reply(
            f"{_user_label(target)}: предупреждение и ограничение на {hours} ч."
        )
    else:
        await _notify(
            bot,
            target["user_id"],
            f"Выдано предупреждение.\nПричина: {reason}",
        )
        await message.reply(f"{_user_label(target)}: предупреждение выдано.")


@router.message(Command("untimeout"))
async def cmd_untimeout(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    actor, actor_role = await _guard_actor(
        message, db, settings, Permission.MANAGE_RESTRICTIONS
    )
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    target = await _resolve_target(
        db, settings, message, parts[1] if len(parts) > 1 else None
    )
    if target is None:
        await message.reply(_target_error())
        return
    reason = _cannot_manage(actor_role, role_of(target))
    if reason:
        await message.reply(reason)
        return
    await db.set_restriction(target["user_id"], until=None, reason=None)
    await db.log_admin_action(
        actor["user_id"], "untimeout", target["user_id"]
    )
    await _notify(
        bot,
        target["user_id"],
        "Временное ограничение снято.",
    )
    await message.reply(
        f"С {_user_label(target)} снято временное ограничение."
    )


@router.message(Command("active"))
async def cmd_active(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_ACTIVE):
        return
    offers = await db.list_by_statuses(_ACTIVE_STATUSES, limit=20)
    if not offers:
        await message.reply("Активных сделок нет.")
        return
    lines = [f"<b>Активные сделки</b> ({len(offers)})", ""]
    for offer in offers:
        lines.append(
            f"#{offer['id']} · {_esc(_short(offer['nft_title']))} · "
            f"{offer['amount']} Stars · {status_label(offer['status'])}"
        )
    await message.reply("\n".join(lines))


@router.message(Command("errors"))
async def cmd_errors(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_ERRORS):
        return
    errors = await db.list_errors(limit=10)
    if not errors:
        await message.reply("Технических ошибок не зафиксировано.")
        return
    lines = ["<b>Последние технические ошибки</b>", ""]
    for item in errors:
        created = datetime.fromtimestamp(
            int(item["created_at"]), tz=settings.tz
        ).strftime("%d.%m.%Y %H:%M")
        lines.append(
            f"{created} · <b>{_esc(item['source'])}</b>\n"
            f"{_esc(_short(item['message'], 180))}"
        )
    await message.reply("\n".join(lines))


# --------------------------------------------------------------- ADMIN / IVAN


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_STATS):
        return
    stats = await db.general_stats()
    lines = [
        "<b>Общая статистика</b>",
        "",
        f"Пользователей: <b>{stats['users']}</b> "
        f"(за сутки: {stats['users_today']})",
        f"Всего сделок: <b>{stats['offers']}</b>",
        f"Активных: <b>{stats['active']}</b>",
        f"Завершено: <b>{stats['completed']}</b>",
        f"Оборот завершённых: <b>{stats['completed_amount']} Stars</b>",
        "",
        "<b>Пользователи по ролям</b>",
    ]
    for role in ALL_ROLES:
        count = stats["roles"].get(role.value, 0)
        if count:
            lines.append(f"{role_label(role)}: {count}")
    lines.append("")
    lines.append("<b>Сделки по статусам</b>")
    for status, count in sorted(stats["offers_by_status"].items()):
        lines.append(f"{status_label(status)}: {count}")
    await message.reply("\n".join(lines))


@router.message(Command("users"))
async def cmd_users(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_USERS_COUNT):
        return
    total = await db.count_users()
    today = await db.count_users_since(int(time.time()) - 86400)
    roles = await db.role_counts()
    lines = [
        "<b>Пользователи</b>",
        "",
        f"Всего: <b>{total}</b>",
        f"За последние 24 часа: <b>{today}</b>",
        "",
    ]
    for role in ALL_ROLES:
        count = roles.get(role.value, 0)
        if count:
            lines.append(f"{role_label(role)}: {count}")
    await message.reply("\n".join(lines))


@router.message(Command("dealsstats"))
async def cmd_dealsstats(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_DEAL_STATS):
        return
    rows = await db.all_offers_by_status()
    if not rows:
        await message.reply("Статистика сделок пуста.")
        return
    lines = ["<b>Статистика сделок</b>", ""]
    total = 0
    for row in rows:
        count = int(row["cnt"])
        total += count
        lines.append(
            f"{status_label(row['status'])}: <b>{count}</b> "
            f"на {int(row['amount'])} Stars"
        )
    lines.append(f"\nВсего: <b>{total}</b>")
    await message.reply("\n".join(lines))


@router.message(Command("broadcast"))
async def cmd_broadcast(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not await _guard(message, db, settings, Permission.BROADCAST):
        return
    parts = (message.text or "").split(maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text and message.reply_to_message is not None:
        text = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or ""
        )
    if not text:
        await message.reply(
            "Использование: <code>/broadcast текст объявления</code> "
            "или ответьте командой на сообщение."
        )
        return
    if len(text) > 3500:
        await message.reply("Текст объявления слишком длинный (максимум 3500).")
        return
    user_ids = await db.all_user_ids()
    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
            sent += 1
        except TelegramBadRequest:
            try:
                await bot.send_message(user_id, text, parse_mode=None)
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(0.03)
    await db.log_admin_action(
        message.from_user.id if message.from_user else 0,
        "broadcast",
        details={"sent": sent, "failed": failed},
    )
    await message.reply(
        f"Рассылка завершена.\nДоставлено: <b>{sent}</b>\n"
        f"Не доставлено: <b>{failed}</b>"
    )


@router.message(Command("settings"))
async def cmd_settings(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    actor = await _guard(message, db, settings, Permission.MANAGE_SETTINGS)
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        support = await db.setting_get(
            "support_contact", settings.support_contact or ""
        )
        min_stars = await db.setting_get(
            "min_offer_stars", str(settings.min_offer_stars)
        )
        max_stars = await db.setting_get(
            "max_offer_stars", str(settings.max_offer_stars)
        )
        await message.reply(
            "<b>Настройки сервиса</b>\n\n"
            f"Контакт поддержки: {_esc(support or '—')}\n"
            f"Мин. сумма: <b>{min_stars}</b> Stars\n"
            f"Макс. сумма: <b>{max_stars}</b> Stars\n"
            f"Срок предложения: <b>{settings.offer_ttl_seconds // 3600} ч</b>\n"
            f"Счёт действует: <b>{settings.payment_window_seconds // 60} мин</b>\n"
            f"Оплата Stars: "
            f"<b>{'включена' if settings.payments_available else 'выключена'}</b>\n"
            f"OWNER ID: {', '.join(str(i) for i in sorted(owner_ids(settings))) or '—'}\n"
            f"ADMIN_IDS из .env: "
            f"{', '.join(str(i) for i in sorted(env_admin_ids(settings))) or '—'}\n\n"
            "<b>Изменение</b>\n"
            "<code>/settings support_contact @username</code>\n"
            "<code>/settings min_offer_stars 10</code>\n"
            "<code>/settings max_offer_stars 100000</code>\n"
            "<code>/settings reset support_contact</code>"
        )
        return

    key = parts[1].strip().lower()
    value = parts[2].strip() if len(parts) > 2 else ""

    if key == "reset":
        if not value:
            await message.reply("Использование: <code>/settings reset KEY</code>")
            return
        await db.setting_delete(value)
        await db.log_admin_action(
            actor["user_id"], "settings_reset", details={"key": value}
        )
        await message.reply(f"Настройка <code>{_esc(value)}</code> сброшена.")
        return

    if key == "support_contact":
        if value.lower() in {"", "none", "off", "-"}:
            await db.setting_delete("support_contact")
            await message.reply("Контакт поддержки очищен.")
        else:
            await db.setting_set("support_contact", value)
            await message.reply(f"Контакт поддержки: {_esc(value)}")
    elif key in {"min_offer_stars", "max_offer_stars"}:
        if not value.isdigit():
            await message.reply("Значение должно быть целым числом Stars.")
            return
        number = int(value)
        if not 1 <= number <= 10_000_000:
            await message.reply("Допустимый диапазон: 1..10 000 000.")
            return
        min_current = int(
            await db.setting_get(
                "min_offer_stars", str(settings.min_offer_stars)
            )
        )
        max_current = int(
            await db.setting_get(
                "max_offer_stars", str(settings.max_offer_stars)
            )
        )
        if key == "min_offer_stars" and number > max_current:
            await message.reply("Минимум не может быть больше максимума.")
            return
        if key == "max_offer_stars" and number < min_current:
            await message.reply("Максимум не может быть меньше минимума.")
            return
        await db.setting_set(key, str(number))
        await message.reply(f"<code>{key}</code> = <b>{number}</b>")
    else:
        await message.reply(
            "Неизвестная настройка. Доступны: support_contact, "
            "min_offer_stars, max_offer_stars."
        )
        return

    await db.log_admin_action(
        actor["user_id"],
        "settings_change",
        details={"key": key, "value": value},
    )


# --------------------------------------------------------------------- OWNER


async def _assign_role(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
    *,
    target_raw: str | None,
    role_raw: str | None,
    command: str,
) -> None:
    """Общая логика выдачи роли для /roles и /setrole."""
    actor = await _guard(message, db, settings, Permission.MANAGE_ROLES)
    if actor is None:
        return
    if not target_raw or not role_raw:
        await message.reply(
            f"Использование: <code>{command} ID_ИЛИ_@username РОЛЬ</code>\n"
            "Роли: USER, TECH ADMIN, ADMIN, SKAM, WORKER, IVAN.\n"
            "OWNER назначается только через OWNER_ID / OWNER_IDS "
            "в .env или Render."
        )
        return
    target = await _resolve_target(db, settings, message, target_raw)
    if target is None:
        await message.reply(_target_error())
        return
    role = parse_role(role_raw)
    if role is None and role_raw.strip().lower() in {
        "remove",
        "снять",
        "сброс",
        "сбросить",
        "нет",
    }:
        role = Role.USER
    if role is None:
        await message.reply(
            "Неизвестная роль. Доступны: USER, TECH ADMIN, ADMIN, SKAM, "
            "WORKER, IVAN."
        )
        return
    if role is Role.OWNER:
        await message.reply(
            "Роль OWNER нельзя выдать командой. Она задаётся только через "
            "OWNER_ID / OWNER_IDS в .env (или переменных Render)."
        )
        return
    if role_of(target) is Role.OWNER:
        await message.reply("Нельзя менять роль владельца бота (OWNER).")
        return
    if target["user_id"] == actor["user_id"]:
        await message.reply(
            "Нельзя изменить собственную роль. OWNER определяется конфигурацией."
        )
        return

    previous = role_of(target)
    await db.set_user_role(target["user_id"], role)
    await db.log_admin_action(
        actor["user_id"],
        command.lstrip("/"),
        target["user_id"],
        {"role": role.value, "previous": previous.value},
    )
    await _notify(
        bot,
        target["user_id"],
        f"Ваша роль изменена: <b>{role_label(role)}</b>.",
    )
    await message.reply(
        f"Пользователь {_user_label(target)} получил роль "
        f"<b>{role_label(role)}</b>."
    )


@router.message(Command("roles"))
async def cmd_roles(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    actor = await _guard(message, db, settings, Permission.MANAGE_ROLES)
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        counts = await db.role_counts()
        lines = [
            "<b>Роли и управление доступом</b>",
            "",
            "Выдать роль: <code>/roles @username ADMIN</code>",
            "Снять роль: <code>/roles @username USER</code>",
            "Можно указать числовой ID вместо @username.",
            "",
            "<b>Роли</b>",
        ]
        for role in ALL_ROLES:
            note = " — задаётся только через OWNER_ID" if role is Role.OWNER else ""
            lines.append(
                f"{role_label(role)}: <b>{counts.get(role.value, 0)}</b>{note}"
            )
        lines.extend(
            [
                "",
                "Роль OWNER нельзя выдать командой: только через "
                "OWNER_ID / OWNER_IDS в .env или Render.",
            ]
        )
        await message.reply("\n".join(lines))
        return
    await _assign_role(
        message,
        db,
        settings,
        bot,
        target_raw=parts[1],
        role_raw=parts[2],
        command="/roles",
    )


@router.message(Command("setrole"))
async def cmd_setrole(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    parts = (message.text or "").split(maxsplit=2)
    await _assign_role(
        message,
        db,
        settings,
        bot,
        target_raw=parts[1] if len(parts) > 1 else None,
        role_raw=parts[2] if len(parts) > 2 else None,
        command="/setrole",
    )


@router.message(Command("removerole"))
async def cmd_removerole(
    message: Message,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    actor = await _guard(message, db, settings, Permission.MANAGE_ROLES)
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    target = await _resolve_target(
        db, settings, message, parts[1] if len(parts) > 1 else None
    )
    if target is None:
        await message.reply(_target_error())
        return
    if role_of(target) is Role.OWNER:
        await message.reply("Нельзя снять роль с владельца бота (OWNER).")
        return
    if target["user_id"] == actor["user_id"]:
        await message.reply("Нельзя изменить собственную роль.")
        return
    previous = role_of(target)
    await db.set_user_role(target["user_id"], Role.USER)
    await db.log_admin_action(
        actor["user_id"],
        "removerole",
        target["user_id"],
        {"previous": previous.value},
    )
    await _notify(
        bot,
        target["user_id"],
        "Дополнительная роль снята. Ваша роль: <b>USER</b>.",
    )
    await message.reply(
        f"С пользователя {_user_label(target)} снята роль "
        f"<b>{role_label(previous)}</b>. Текущая роль: USER."
    )


@router.message(Command("admins"))
async def cmd_admins(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_FULL_STATS):
        return
    staff = await db.list_staff_users()
    if not staff:
        await message.reply("Список администраторов пуст.")
        return
    lines = ["<b>Администраторы</b>", ""]
    for record in staff:
        lines.append(
            f"{role_label(role_of(record))} · {_user_label(record)} · "
            f"<code>{record['user_id']}</code>"
        )
    await message.reply("\n".join(lines))


@router.message(Command("backup"))
async def cmd_backup(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    actor = await _guard(message, db, settings, Permission.BACKUP)
    if actor is None:
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = settings.database_path.parent.parent / "backups" / (
        f"backup_{stamp}.sqlite3"
    )
    try:
        await db.backup_to(path)
    except Exception as exc:
        logger.exception("Не удалось создать резервную копию")
        await db.add_error("backup", str(exc))
        await message.reply("Не удалось создать резервную копию. Смотрите /errors.")
        return
    await db.log_admin_action(
        actor["user_id"], "backup", details={"path": str(path)}
    )
    size = path.stat().st_size
    try:
        await message.answer_document(
            FSInputFile(path),
            caption=f"Резервная копия базы данных\n{size} байт",
        )
    except TelegramAPIError:
        await message.reply(f"Копия создана: <code>{_esc(path)}</code>")


@router.message(Command("maintenance"))
async def cmd_maintenance(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    actor = await _guard(message, db, settings, Permission.MANAGE_MAINTENANCE)
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=2)
    mode = parts[1].strip().lower() if len(parts) > 1 else ""
    if mode not in {"on", "off"}:
        active, until = await db.maintenance_state()
        state = "включён" if active else "выключен"
        await message.reply(
            f"Технический режим сейчас <b>{state}</b>.\n\n"
            "Использование: <code>/maintenance on</code> или "
            "<code>/maintenance off</code>."
        )
        return
    if mode == "on":
        reason = parts[2].strip() if len(parts) > 2 else "Техническое обслуживание"
        await db.set_maintenance(until=None, reason=reason, admin_id=actor["user_id"])
        await db.log_admin_action(
            actor["user_id"], "maintenance_on", details={"reason": reason}
        )
        await message.reply(
            "Технический режим включён до команды <code>/open</code>.\n"
            "Обычные пользователи получают уведомление об обслуживании."
        )
    else:
        await db.clear_maintenance()
        await db.log_admin_action(actor["user_id"], "maintenance_off")
        await message.reply("Технический режим выключен.")


@router.message(Command("zakrit"))
async def cmd_zakrit(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    actor = await _guard(message, db, settings, Permission.MANAGE_MAINTENANCE)
    if actor is None:
        return
    until = int(time.time()) + 12 * 3600
    await db.set_maintenance(
        until=until,
        reason="Плановые работы",
        admin_id=actor["user_id"],
    )
    await db.log_admin_action(
        actor["user_id"], "zakrit", details={"until": until}
    )
    finish = datetime.fromtimestamp(until, tz=settings.tz).strftime(
        "%d.%m.%Y %H:%M"
    )
    await message.reply(
        "Бот переведён в технический режим на 12 часов.\n"
        f"Автоматическое включение: <b>{finish}</b>.\n"
        "Досрочно: <code>/open</code>."
    )


@router.message(Command("open"))
async def cmd_open(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    actor = await _guard(message, db, settings, Permission.MANAGE_MAINTENANCE)
    if actor is None:
        return
    await db.clear_maintenance()
    await db.log_admin_action(actor["user_id"], "open")
    await message.reply("Технический режим выключен. Бот снова принимает заявки.")


@router.message(Command("adminlog"))
async def cmd_adminlog(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    if not await _guard(message, db, settings, Permission.VIEW_FULL_STATS):
        return
    entries = await db.list_admin_log(limit=20)
    if not entries:
        await message.reply("Журнал административных действий пуст.")
        return
    lines = ["<b>Журнал административных действий</b>", ""]
    for item in entries:
        created = datetime.fromtimestamp(
            int(item["created_at"]), tz=settings.tz
        ).strftime("%d.%m.%Y %H:%M")
        target = f" → <code>{item['target_id']}</code>" if item["target_id"] else ""
        lines.append(
            f"{created} · <code>{item['admin_id']}</code>{target} · "
            f"{_esc(item['action'])}"
        )
    await message.reply("\n".join(lines))
