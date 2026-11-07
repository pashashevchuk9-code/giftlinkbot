from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BusinessConnection,
    CallbackQuery,
    ChatMemberUpdated,
    ChosenInlineResult,
    ErrorEvent,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
    PreCheckoutQuery,
)

from access import (
    can_view_any_deal,
    get_actor,
    is_payment_admin,
    require_message_permission,
    role_of,
)
from admin_handlers import router as admin_router
from config import Settings
from database import Database
from deals import DealService, _now
from keyboards import main_menu_keyboard, offer_main_keyboard
from nft import parse_nft_link
from menu_handlers import WELCOME_TEXT
from menu_handlers import router as menu_router
from roles import Permission, Role, has_permission

logger = logging.getLogger(__name__)
router = Router(name="deals")


async def _admin_private_allowed(
    message: Message,
    db: Database,
    settings: Settings,
    permission: Permission = Permission.MANAGE_REFUNDS,
) -> bool:
    if message.from_user is None:
        await message.reply("Не удалось определить пользователя.")
        return False
    return await require_message_permission(
        message, db, settings, permission, private_only=True
    )


def _help_text(settings: Settings, in_group: bool = False) -> str:
    ack = (
        "Оплата включена."
        if settings.payments_available
        else "Оплата Stars выключена до настройки ADMIN_IDS и подтверждения ручных выплат."
    )
    ttl_hours = max(1, settings.offer_ttl_seconds // 3600)
    base = (
        "<b>Как предложить обмен NFT</b>\n\n"
        "В группе ответьте на сообщение продавца командой:\n"
        "<code>@бот https://t.me/nft/Name-123 100</code>\n\n"
        "Или укажите продавца явно:\n"
        "<code>@бот @seller https://t.me/nft/Name-123 100</code>\n\n"
        "Можно использовать и команду:\n"
        "<code>/offer@бот https://t.me/nft/Name-123 100</code>\n\n"
        f"Где <code>100</code> — количество Stars. Предложение действует {ttl_hours} ч.\n\n"
        "Продавец нажимает «Принять» или «Отклонить». После принятия он "
        "подтверждает сделку, покупатель оплачивает официальный счёт Telegram Stars, "
        "продавец передаёт NFT, покупатель подтверждает получение.\n\n"
        f"{ack}"
    )
    if settings.support_contact:
        base += f"\n\nПоддержка: {html.escape(settings.support_contact)}"
    if not in_group:
        base += (
            "\n\nПредложения создаются в групповом чате. Добавьте бота в группу, "
            "где находятся покупатель и продавец."
        )
    return base


async def _touch_user(db: Database, message: Message) -> None:
    if message.from_user and not message.from_user.is_bot:
        await db.upsert_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, settings: Settings) -> None:
    await _touch_user(db, message)
    if message.chat.type == ChatType.PRIVATE.value:
        if message.from_user is not None:
            record = await get_actor(db, settings, message.from_user)
            if role_of(record) is Role.SKAM:
                # Страховка: middleware обычно не пропускает SKAM сюда.
                await message.answer(
                    "Аккаунт имеет ограниченный доступ. Функции бота недоступны."
                )
                return
        await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())
    else:
        await message.reply(
            "Бот для предложений NFT за Stars. Напишите /help, чтобы увидеть формат."
        )


@router.message(Command("help"))
async def cmd_help(message: Message, db: Database, settings: Settings) -> None:
    await _touch_user(db, message)
    await message.reply(_help_text(settings, in_group=message.chat.type != ChatType.PRIVATE.value))


@router.message(Command("whoami"))
async def cmd_whoami(
    message: Message, db: Database, settings: Settings
) -> None:
    if message.from_user is None:
        return
    record = await get_actor(db, settings, message.from_user)
    role = role_of(record)
    username = f"@{message.from_user.username}" if message.from_user.username else "без username"
    await message.reply(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Username: {username}\n"
        f"Роль: <b>{role.value}</b>"
    )


@router.message(Command("myoffers", "deals"))
async def cmd_myoffers(
    message: Message, db: Database, service: DealService, settings: Settings
) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(
        message, db, settings, Permission.VIEW_OWN_OFFERS
    ):
        return
    await _touch_user(db, message)
    await message.reply(await service.user_offers_text(message.from_user.id))


@router.message(Command("deal"))
async def cmd_deal(
    message: Message, db: Database, service: DealService, settings: Settings
) -> None:
    if message.from_user is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /deal НОМЕР")
        return
    offer_id = int(parts[1].strip())
    offer = await db.get_offer(offer_id)
    if offer is None:
        await message.reply("Сделка не найдена.")
        return
    user_id = message.from_user.id
    is_seller = offer.get("seller_id") == user_id or (
        offer.get("seller_id") is None
        and offer.get("seller_username")
        and message.from_user.username
        and offer["seller_username"].lower() == message.from_user.username.lower()
    )
    if (
        offer["buyer_id"] != user_id
        and not is_seller
        and not await can_view_any_deal(db, settings, user_id)
    ):
        await message.reply("У вас нет доступа к этой сделке.")
        return
    await message.reply(await service.deal_details_text(offer_id))


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    db: Database,
    service: DealService,
    settings: Settings,
) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(
        message, db, settings, Permission.USE_STANDARD
    ):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /cancel НОМЕР")
        return
    await message.reply(await service.cancel_by_command(int(parts[1].strip()), message.from_user))


@router.message(Command("business"))
async def cmd_business(message: Message, service: DealService) -> None:
    if message.from_user is None:
        return
    await message.reply(await service.business_status_text(message.from_user.id))


@router.message(Command("admin"))
async def cmd_admin(
    message: Message, db: Database, service: DealService, settings: Settings
) -> None:
    if not await _admin_private_allowed(message, db, settings):
        return
    await message.reply(await service.admin_stats_text())
    await message.reply(
        "Команды: /pending, /payout НОМЕР ССЫЛКА, /refund НОМЕР, /reconcile НОМЕР"
    )


@router.message(Command("pending"))
async def cmd_pending(
    message: Message, db: Database, service: DealService, settings: Settings
) -> None:
    if not await _admin_private_allowed(message, db, settings):
        return
    await message.reply(await service.admin_pending_text())


@router.message(Command("refund"))
async def cmd_refund(
    message: Message, db: Database, service: DealService, settings: Settings
) -> None:
    if not await _admin_private_allowed(message, db, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /refund НОМЕР")
        return
    result = await service.refund(int(parts[1].strip()), message.from_user.id)
    await db.log_admin_action(
        message.from_user.id, "refund", int(parts[1].strip())
    )
    await message.reply(result)


@router.message(Command("payout"))
async def cmd_payout(
    message: Message, db: Database, service: DealService, settings: Settings
) -> None:
    if not await _admin_private_allowed(message, db, settings):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].strip().isdigit():
        await message.reply(
            "Использование: /payout НОМЕР ССЫЛКА_ИЛИ_НОМЕР_ВЫПЛАТЫ\n"
            "Ссылка подтверждает, что оператор уже выполнил внешнюю выплату."
        )
        return
    result = await service.payout(
        int(parts[1].strip()),
        parts[2].strip(),
        message.from_user.id,
    )
    await db.log_admin_action(
        message.from_user.id,
        "payout",
        int(parts[1].strip()),
        {"reference": parts[2].strip()},
    )
    await message.reply(result)


@router.message(Command("reconcile"))
async def cmd_reconcile(
    message: Message, db: Database, service: DealService, settings: Settings
) -> None:
    if not await _admin_private_allowed(message, db, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /reconcile НОМЕР")
        return
    await message.reply(
        await service.reconcile(int(parts[1].strip()), message.from_user.id)
    )


@router.message(Command("offer"))
async def cmd_offer(
    message: Message, service: DealService, db: Database, settings: Settings
) -> None:
    await _touch_user(db, message)
    if not await require_message_permission(
        message, db, settings, Permission.CREATE_OFFER
    ):
        return
    if message.chat.type == ChatType.PRIVATE.value:
        await message.reply(
            "Предложения создаются в групповом чате. Добавьте бота в группу "
            "и отправьте команду ответом на сообщение продавца."
        )
        return
    await service.parse_and_create(message)


@router.message(
    F.chat.type.in_({ChatType.GROUP.value, ChatType.SUPERGROUP.value}),
    F.text,
    ~F.text.startswith("/"),
)
async def group_offer_message(
    message: Message,
    service: DealService,
    db: Database,
    settings: Settings,
) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(
        message, db, settings, Permission.CREATE_OFFER
    ):
        return
    await service.parse_and_create(message)


@router.callback_query(F.data.startswith("offer:"))
async def on_offer_callback(
    callback: CallbackQuery,
    service: DealService,
    db: Database,
    settings: Settings,
) -> None:
    if callback.data is None:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[1].isdigit():
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return
    action = parts[2]
    if action == "admin_refund":
        if not await is_payment_admin(db, settings, callback.from_user.id):
            await db.log_admin_action(
                callback.from_user.id,
                "access_denied",
                details={"permission": "admin_refund"},
            )
            await callback.answer("Только администратор.", show_alert=True)
            return
        if (
            callback.message is None
            or callback.message.chat.type != ChatType.PRIVATE.value
        ):
            await callback.answer(
                "Возврат выполняется в личном чате с ботом.",
                show_alert=True,
            )
            return
        result = await service.refund(int(parts[1]), callback.from_user.id)
        await db.log_admin_action(
            callback.from_user.id, "refund", int(parts[1])
        )
        await callback.answer(result[:200], show_alert=True)
        return

    handlers = {
        "accept": service.on_accept,
        "reject": service.on_reject,
        "confirm": service.on_confirm,
        "cancel": service.on_cancel,
        "seller_sent": service.on_seller_sent,
        "buyer_confirm": service.on_buyer_confirm,
        "dispute": service.on_dispute,
    }
    handler = handlers.get(action)
    if handler is None:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return
    blocked = await service.access_error_for(callback.from_user.id)
    if blocked:
        await callback.answer(blocked[:200], show_alert=True)
        return
    await handler(callback)


@router.pre_checkout_query()
async def on_pre_checkout(
    query: PreCheckoutQuery,
    bot: Bot,
    service: DealService,
) -> None:
    try:
        ok, error = await service.handle_pre_checkout(query)
    except Exception:
        logger.exception("Ошибка проверки pre_checkout")
        ok, error = False, "Не удалось проверить счёт. Попробуйте позже."
    await bot.answer_pre_checkout_query(
        pre_checkout_query_id=query.id,
        ok=ok,
        error_message=error,
    )


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, service: DealService) -> None:
    await service.handle_successful_payment(message)


@router.business_connection()
async def on_business_connection(
    connection: BusinessConnection,
    service: DealService,
) -> None:
    await service.on_business_connection(connection)


@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated, bot: Bot) -> None:
    if update.chat.type not in {ChatType.GROUP.value, ChatType.SUPERGROUP.value}:
        return
    if update.new_chat_member.status not in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    }:
        return
    try:
        await bot.send_message(
            update.chat.id,
            "Бот подключён. Отправьте /help, чтобы увидеть формат предложения NFT за Stars.",
        )
    except TelegramAPIError:
        pass


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot, db: Database, settings: Settings) -> bool:
    exc = event.exception
    if exc is not None:
        logger.error(
            "Необработанная ошибка",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        try:
            import traceback

            await db.add_error(
                "handler",
                f"{type(exc).__name__}: {exc}",
                traceback.format_exc(),
            )
        except Exception:
            pass
    else:
        logger.error("Необработанная ошибка без exception")
    update = event.update
    if update.callback_query is not None:
        try:
            await update.callback_query.answer(
                "Произошла ошибка. Попробуйте ещё раз.", show_alert=True
            )
        except TelegramAPIError:
            pass
    admin_ids: set[int] = set(settings.admin_ids)
    try:
        admin_ids.update(await db.list_staff_ids())
    except Exception:
        pass
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "Произошла необработанная ошибка. Подробности в логах и /errors.",
            )
        except TelegramAPIError:
            pass
    return True


# ------------------------------------------------------------------ INLINE MODE


@router.inline_query()
async def on_inline_query(
    inline_query: InlineQuery,
    db: Database,
    settings: Settings,
    service: DealService,
    nft: NFTResolver,
) -> None:
    if inline_query.from_user is None:
        return
    actor = await get_actor(db, settings, inline_query.from_user)
    role = role_of(actor)
    if role is Role.SKAM:
        await inline_query.answer([], cache_time=1, is_personal=True)
        return
    if not has_permission(role, Permission.CREATE_OFFER):
        await inline_query.answer([], cache_time=1, is_personal=True)
        return

    text = (inline_query.query or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await inline_query.answer(
            [],
            cache_time=1,
            is_personal=True,
            switch_pm_text="???????: ??????_??_NFT ????",
            switch_pm_parameter="inline",
        )
        return

    nft_url = parts[0]
    amount_raw = parts[1]
    nft_slug = parse_nft_link(nft_url)
    if nft_slug is None:
        await inline_query.answer(
            [],
            cache_time=1,
            is_personal=True,
            switch_pm_text="???????????? ?????? ?? NFT",
            switch_pm_parameter="inline",
        )
        return
    if not amount_raw.isdigit() or int(amount_raw) <= 0:
        await inline_query.answer(
            [],
            cache_time=1,
            is_personal=True,
            switch_pm_text="???? ?????? ???? ?????? ?????? ????",
            switch_pm_parameter="inline",
        )
        return
    amount = int(amount_raw)

    # ???????? ??????? ?? ????????.
    min_stars = await service.effective_min_stars()
    max_stars = await service.effective_max_stars()
    if amount < min_stars or amount > max_stars:
        await inline_query.answer(
            [],
            cache_time=1,
            is_personal=True,
            switch_pm_text=f"?????: ?? {min_stars} ?? {max_stars} Stars",
            switch_pm_parameter="inline",
        )
        return

    # ?????????? NFT.
    try:
        info = await nft.resolve(nft_slug)
    except Exception:
        info = None
    nft_title = getattr(info, "title", None) or nft_slug
    nft_image_url = getattr(info, "image_url", None)
    nft_description = getattr(info, "description", None)
    nft_owner_label = getattr(info, "owner_label", None)

    now_ts = _now()
    expires_at = now_ts + settings.offer_ttl_seconds
    offer_id = await db.create_offer(
        group_chat_id=0,
        buyer_id=inline_query.from_user.id,
        buyer_username=inline_query.from_user.username,
        buyer_name=" ".join(
            p for p in (inline_query.from_user.first_name, inline_query.from_user.last_name) if p
        ),
        seller_id=None,
        seller_username=None,
        seller_name=None,
        nft_url=nft_url,
        nft_slug=nft_slug,
        nft_title=nft_title,
        nft_image_url=nft_image_url,
        nft_description=nft_description,
        nft_owner_label=nft_owner_label,
        amount=amount,
        expires_at=expires_at,
    )

    offer = await db.get_offer(offer_id)
    assert offer is not None
    card_text = service._caption(offer)
    keyboard = offer_main_keyboard(offer_id)

    result = InlineQueryResultArticle(
        id=str(offer_id),
        title=f"?????????? {amount} Stars ?? {nft_title}",
        description=f"NFT: {nft_title}",
        input_message_content=InputTextMessageContent(
            message_text=card_text,
            parse_mode="HTML",
            link_preview_options={"is_disabled": True},
        ),
        reply_markup=keyboard,
    )
    await inline_query.answer([result], cache_time=0, is_personal=True)


@router.chosen_inline_result()
async def on_chosen_inline_result(
    chosen: ChosenInlineResult,
    db: Database,
) -> None:
    try:
        offer_id = int(chosen.result_id)
    except (TypeError, ValueError):
        return
    if chosen.inline_message_id:
        await db.set_inline_message(offer_id, chosen.inline_message_id)


router.include_router(menu_router)
router.include_router(admin_router)
