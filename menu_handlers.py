"""Главное меню, профиль и пользовательские разделы."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from access import (
    can_view_any_deal,
    get_actor,
    require_callback_permission,
    require_message_permission,
    role_of,
)
from config import Settings
from constants import OfferStatus, status_label
from database import Database
from deals import DealService
from keyboards import (
    back_to_menu_keyboard,
    main_menu_keyboard,
    notifications_keyboard,
    offer_list_keyboard,
)
from roles import Permission, Role, command_sections, role_label

router = Router(name="menu")

WELCOME_TEXT = (
    "👋 Добро пожаловать!\n\n"
    "Вас приветствует NFT & Stars Exchange — независимый сервис "
    "для предложений обмена Telegram NFT и Stars.\n\n"
    "Здесь вы можете:\n\n"
    "- Создавать предложения обмена.\n"
    "- Просматривать активные сделки.\n"
    "- Управлять своими предложениями.\n"
    "- Следить за статусом обменов.\n"
    "- Получать уведомления о новых предложениях.\n\n"
    "Выберите нужный раздел ниже 👇"
)

RULES_TEXT = (
    "<b>Правила обмена</b>\n\n"
    "1. Предложение создаётся в групповом чате, где находятся покупатель "
    "и продавец.\n"
    "2. Покупатель отправляет команду ответом на сообщение продавца:\n"
    "<code>@бот https://t.me/nft/Name-123 100</code>\n"
    "или указывает продавца явно:\n"
    "<code>@бот @username https://t.me/nft/Name-123 100</code>\n"
    "3. Срок действия предложения — ровно 48 часов.\n"
    "4. Продавец принимает или отклоняет предложение кнопками на карточке.\n"
    "5. После принятия продавец подтверждает сделку, а покупатель оплачивает "
    "официальный счёт Telegram Stars.\n"
    "6. Продавец передаёт NFT, покупатель подтверждает получение.\n"
    "7. Выплата продавцу выполняется оператором после подтверждения.\n"
    "8. Обмены вне бота и предоплата без карточки не защищены.\n\n"
    "Проверяйте ссылку на NFT, сумму и username продавца перед оплатой."
)

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

_CLOSED_STATUSES: tuple[str, ...] = (
    OfferStatus.COMPLETED.value,
    OfferStatus.REJECTED.value,
    OfferStatus.EXPIRED.value,
    OfferStatus.CANCELLED.value,
    OfferStatus.REFUNDED.value,
    OfferStatus.FAILED.value,
)


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _fmt_date(timestamp: int | None, settings: Settings) -> str:
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(int(timestamp), tz=settings.tz).strftime("%d.%m.%Y")


def _username(record: dict[str, Any]) -> str:
    username = record.get("username")
    return f"@{_esc(username)}" if username else "—"


def _offer_line(offer: dict[str, Any]) -> str:
    title = str(offer.get("nft_title") or "NFT")
    if len(title) > 40:
        title = title[:39] + "…"
    return (
        f"#{offer['id']} · {_esc(title)} · {offer['amount']} Stars · "
        f"{status_label(offer['status'])}"
    )


async def profile_text(
    db: Database, settings: Settings, record: dict[str, Any]
) -> str:
    completed = await db.count_completed_deals(record["user_id"])
    return (
        "<b>Ваш профиль</b>\n\n"
        f"ID: <code>{record['user_id']}</code>\n"
        f"Username: {_username(record)}\n"
        f"Role: <b>{role_label(role_of(record))}</b>\n"
        f"Регистрация: {_fmt_date(record.get('registered_at'), settings)}\n"
        f"Завершённые сделки: <b>{completed}</b>"
    )


async def _offers_text(db: Database, user_id: int) -> tuple[str, list[int]]:
    offers = await db.list_user_offers_by_statuses(
        user_id, _ACTIVE_STATUSES, limit=10
    )
    if not offers:
        return (
            "<b>Мои предложения</b>\n\n"
            "Активных предложений нет.\n\n"
            "Создать предложение можно в группе командой:\n"
            "<code>@бот https://t.me/nft/Name-123 100</code>",
            [],
        )
    lines = ["<b>Мои предложения</b>", ""]
    for offer in offers:
        lines.append(_offer_line(offer))
    return "\n".join(lines), [int(offer["id"]) for offer in offers]


async def _history_text(db: Database, user_id: int) -> tuple[str, list[int]]:
    offers = await db.list_user_offers_by_statuses(
        user_id, _CLOSED_STATUSES, limit=10
    )
    if not offers:
        return "<b>История сделок</b>\n\nЗавершённых сделок пока нет.", []
    lines = ["<b>История сделок</b>", ""]
    for offer in offers:
        lines.append(_offer_line(offer))
    return "\n".join(lines), [int(offer["id"]) for offer in offers]


async def _notifications_text(
    db: Database, user_id: int
) -> tuple[str, bool]:
    enabled = await db.notifications_enabled(user_id)
    await db.mark_notifications_read(user_id)
    items = await db.list_notifications(user_id, limit=10)
    lines = [
        "<b>Уведомления</b>",
        "",
        f"Новые предложения: {'включены' if enabled else 'выключены'}.",
    ]
    if items:
        lines.append("")
        for item in items:
            created = datetime.fromtimestamp(
                int(item["created_at"])
            ).strftime("%d.%m.%Y %H:%M")
            text = str(item["text"]).replace("\n", " ")
            if len(text) > 160:
                text = text[:159] + "…"
            lines.append(f"{created} · {_esc(text)}")
    else:
        lines.append("\nПока уведомлений нет.")
    return "\n".join(lines), enabled


async def _support_text(db: Database, settings: Settings) -> str:
    override = await db.setting_get("support_contact")
    contact = override or settings.support_contact
    if contact:
        return (
            "<b>Поддержка</b>\n\n"
            f"Обратитесь: {_esc(contact)}\n\n"
            "Опишите номер сделки и суть вопроса."
        )
    return (
        "<b>Поддержка</b>\n\n"
        "Контакт поддержки пока не указан.\n"
        "Администратор может задать его командой:\n"
        "<code>/settings support_contact @username</code>"
    )


def _create_text(settings: Settings) -> str:
    ttl_hours = settings.offer_ttl_seconds // 3600
    return (
        "<b>Создать предложение</b>\n\n"
        "Предложение создаётся в групповом чате, где есть продавец.\n\n"
        "1. Добавьте бота в группу.\n"
        "2. Ответьте на сообщение продавца командой:\n"
        "<code>@бот https://t.me/nft/Name-123 100</code>\n\n"
        "Или укажите продавца явно:\n"
        "<code>@бот @username https://t.me/nft/Name-123 100</code>\n\n"
        f"Срок действия — {ttl_hours} ч. "
        "Продавец принимает или отклоняет предложение кнопками."
    )


async def _show(
    callback: CallbackQuery,
    text: str,
    keyboard=None,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    if callback.message.chat.type == "private":
        try:
            await callback.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                link_preview_options={"is_disabled": True},
            )
            await callback.answer()
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in (exc.message or "").lower():
                await callback.answer()
                return
    try:
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            link_preview_options={"is_disabled": True},
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(Command("profile"))
async def cmd_profile(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(
        message, db, settings, Permission.VIEW_PROFILE
    ):
        return
    record = await get_actor(db, settings, message.from_user)
    await message.reply(await profile_text(db, settings, record))


@router.message(Command("history"))
async def cmd_history(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(
        message, db, settings, Permission.VIEW_HISTORY
    ):
        return
    text, _ = await _history_text(db, message.from_user.id)
    await message.reply(text)


@router.message(Command("rules"))
async def cmd_rules(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(
        message, db, settings, Permission.VIEW_RULES
    ):
        return
    await message.reply(RULES_TEXT)


@router.message(Command("comand"))
async def cmd_comand(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    record = await get_actor(db, settings, message.from_user)
    role = role_of(record)
    if role is Role.SKAM:
        await message.reply(
            "Аккаунт имеет ограниченный доступ. Команды недоступны."
        )
        return
    if not await require_message_permission(
        message, db, settings, Permission.USE_STANDARD
    ):
        return
    lines = [f"<b>Команды для роли {role_label(role)}</b>", ""]
    for title, commands in command_sections(role):
        lines.append(f"<b>{title}</b>")
        for name, description in commands:
            lines.append(f"<code>{name}</code> — {description}")
        lines.append("")
    await message.reply("\n".join(lines).strip())


@router.callback_query(F.data.startswith("menu:"))
async def on_menu(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    service: DealService,
) -> None:
    if not await require_callback_permission(
        callback, db, settings, Permission.USE_STANDARD
    ):
        return
    data = callback.data or ""
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "back"

    if action == "back":
        await _show(callback, WELCOME_TEXT, main_menu_keyboard())
        return

    if action == "create":
        await _show(callback, _create_text(settings), back_to_menu_keyboard())
        return

    if action == "offers":
        text, ids = await _offers_text(db, callback.from_user.id)
        keyboard = offer_list_keyboard(ids) if ids else back_to_menu_keyboard()
        await _show(callback, text, keyboard)
        return

    if action == "history":
        text, ids = await _history_text(db, callback.from_user.id)
        keyboard = offer_list_keyboard(ids) if ids else back_to_menu_keyboard()
        await _show(callback, text, keyboard)
        return

    if action == "notifications":
        text, enabled = await _notifications_text(
            db, callback.from_user.id
        )
        await _show(callback, text, notifications_keyboard(enabled))
        return

    if action == "notif_toggle":
        enabled = await db.notifications_enabled(callback.from_user.id)
        await db.set_notifications_enabled(
            callback.from_user.id, not enabled
        )
        await db.log_admin_action(
            callback.from_user.id,
            "notifications_toggle",
            details={"enabled": not enabled},
        )
        text, state = await _notifications_text(db, callback.from_user.id)
        await _show(callback, text, notifications_keyboard(state))
        return

    if action == "rules":
        await _show(callback, RULES_TEXT, back_to_menu_keyboard())
        return

    if action == "support":
        await _show(
            callback,
            await _support_text(db, settings),
            back_to_menu_keyboard(),
        )
        return

    if action == "profile":
        record = await get_actor(db, settings, callback.from_user)
        await _show(
            callback,
            await profile_text(db, settings, record),
            back_to_menu_keyboard(),
        )
        return

    if action == "deal" and len(parts) == 3 and parts[2].isdigit():
        offer_id = int(parts[2])
        offer = await db.get_offer(offer_id)
        if offer is None:
            await callback.answer("Сделка не найдена.", show_alert=True)
            return
        allowed = (
            offer["buyer_id"] == callback.from_user.id
            or offer.get("seller_id") == callback.from_user.id
            or await can_view_any_deal(db, settings, callback.from_user.id)
        )
        if not allowed:
            await callback.answer(
                "У вас нет доступа к этой сделке.", show_alert=True
            )
            return
        text = await service.deal_details_text(offer_id)
        await _show(callback, text, back_to_menu_keyboard())
        return

    await callback.answer("Раздел не найден.", show_alert=True)
