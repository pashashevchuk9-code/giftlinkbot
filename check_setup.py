"""Безопасная проверка конфигурации, базы, парсеров и связи с Telegram.

Не печатает BOT_TOKEN. По умолчанию проверяет и Telegram (getMe).
Запуск: python check_setup.py
Только локальные проверки: python check_setup.py --offline
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.types import Chat, Message, User

from config import ConfigError, Settings
from database import Database
from gifts import GiftService
from nft import NFTResolver, parse_nft_link
from parsing import OfferParseError, parse_offer_message
from roles import Permission, Role, has_permission, parse_role


def role_checks() -> None:
    assert has_permission(Role.USER, Permission.CREATE_OFFER)
    assert has_permission(Role.WORKER, Permission.CREATE_OFFER)
    assert has_permission(Role.TECH_ADMIN, Permission.BAN_USERS)
    assert not has_permission(Role.TECH_ADMIN, Permission.BROADCAST)
    assert has_permission(Role.ADMIN, Permission.BROADCAST)
    assert not has_permission(Role.ADMIN, Permission.BAN_USERS)
    assert has_permission(Role.IVAN, Permission.VIEW_STATS)
    assert not has_permission(Role.IVAN, Permission.MANAGE_ROLES)
    assert not has_permission(Role.IVAN, Permission.MANAGE_MAINTENANCE)
    assert has_permission(Role.OWNER, Permission.MANAGE_ROLES)
    assert not has_permission(Role.SKAM, Permission.CREATE_OFFER)
    assert parse_role("TECH_ADMIN") is Role.TECH_ADMIN
    assert parse_role("Иван") is Role.IVAN
    assert parse_role("скам") is Role.SKAM
    print("[OK] 7 ролей и матрица прав")


def local_checks() -> None:
    assert parse_nft_link("https://t.me/nft/PlushPepe-1") == "PlushPepe-1"
    assert parse_nft_link("https://example.com/nft/1") is None

    bot_username = "GiftIinkBot"
    chat = Chat(id=-100123, type="supergroup", title="Check")
    buyer = User(id=1, is_bot=False, first_name="Buyer", username="buyer")
    seller = User(id=2, is_bot=False, first_name="Seller", username="seller")
    reply = Message(
        message_id=9,
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=seller,
        text="My NFT",
    )
    message = Message(
        message_id=10,
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=buyer,
        text=f"@{bot_username} https://t.me/nft/PlushPepe-1 100",
        reply_to_message=reply,
    )
    request = parse_offer_message(message, bot_username, 1, 1_000_000)
    assert request is not None and request.amount == 100
    try:
        parse_offer_message(
            Message(
                message_id=11,
                date=datetime.now(timezone.utc),
                chat=chat,
                from_user=buyer,
                text=f"@{bot_username} https://t.me/nft/PlushPepe-1 100",
            ),
            bot_username,
            1,
            1_000_000,
        )
    except OfferParseError:
        pass
    else:
        raise AssertionError("Парсер должен требовать продавца")

    from types import SimpleNamespace
    from aiogram.types import OwnedGiftUnique

    gift = SimpleNamespace(name="Plush Pepe #1", base_name="Plush Pepe", number=1)
    item = OwnedGiftUnique.model_construct(
        type="unique",
        gift=gift,
        send_date=0,
        owned_gift_id="check",
        can_be_transferred=True,
        transfer_star_count=0,
    )
    assert GiftService._find_unique([item], "PlushPepe-1") is item
    print("[OK] Парсинг ссылки, команды и сопоставление NFT")


async def database_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "check.sqlite3")
        await db.init()
        now = int(time.time())
        offer_id = await db.create_offer(
            group_chat_id=-100123,
            buyer_id=1,
            buyer_username="buyer",
            buyer_name="Buyer",
            seller_id=2,
            seller_username="seller",
            seller_name="Seller",
            nft_url="https://t.me/nft/PlushPepe-1",
            nft_slug="PlushPepe-1",
            nft_title="Plush Pepe #1",
            nft_image_url=None,
            nft_description=None,
            nft_owner_label=None,
            amount=100,
            expires_at=now + 3600,
        )
        assert await db.transition(offer_id, {"pending"}, "accepted", accepted_at=now)
        assert await db.set_payment_pending(offer_id, "n", "https://t.me/$check", now + 60)
        assert await db.mark_paid(offer_id, 1, 100, "n", "check-charge", None, 100)
        assert not await db.mark_paid(offer_id, 1, 100, "n", "check-charge", None, 100)
        assert await db.mark_nft_transferred(offer_id, method="manual")
        assert await db.mark_payout_pending(offer_id)
        assert await db.mark_completed(offer_id, "manual-check", 1)
        assert await db.charge_exists("check-charge")
        assert await db.claim_refund(
            charge_id="check-charge",
            offer_id=offer_id,
            user_id=1,
            amount=100,
            reason="check",
        )
        assert not await db.claim_refund(
            charge_id="check-charge",
            offer_id=offer_id,
            user_id=1,
            amount=100,
            reason="check-again",
        )
        user = await db.ensure_user(
            1, "buyer", "Buyer", None, owner_ids=frozenset({1})
        )
        assert user["role"] == Role.OWNER.value
        await db.ensure_user(2, "seller", "Seller", None)
        await db.set_user_role(2, Role.TECH_ADMIN)
        assert (await db.get_user(2))["role"] == Role.TECH_ADMIN.value
        await db.set_ban(2, banned=True, admin_id=1, reason="check")
        assert (await db.get_user(2))["is_banned"] == 1
        await db.set_ban(2, banned=False, admin_id=1)
        await db.add_warning(2, 1, "check")
        assert await db.count_warnings(2) == 1
        await db.set_restriction(2, until=now + 60, reason="check")
        assert (await db.get_user(2))["restriction_until"] == now + 60
        await db.set_maintenance(until=now + 3600, admin_id=1)
        active, until = await db.maintenance_state()
        assert active and until == now + 3600
        await db.clear_maintenance()
        assert not (await db.maintenance_state())[0]
        await db.log_admin_action(1, "check", 2)
        assert await db.list_admin_log(1)
        await db.set_notifications_enabled(1, False)
        assert not await db.notifications_enabled(1)
        await db.close()
    print("[OK] SQLite, переходы статусов, защита от повторной оплаты и возврата")


async def telegram_check(settings: Settings) -> str | None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            print("[FAIL] Telegram отклонил BOT_TOKEN. Проверьте .env.")
            return None
        except TelegramAPIError as exc:
            print(f"[FAIL] Ошибка Telegram API: {exc.message}")
            return None

        print(f"[OK] Telegram: @{me.username} (id={me.id})")
        if not me.can_join_groups:
            print("[WARN] В BotFather бот не может вступать в группы.")
        try:
            balance = await bot.get_my_star_balance()
            print(f"[OK] Баланс бота: {balance.amount} Stars")
        except TelegramAPIError as exc:
            print(f"[WARN] Баланс Stars недоступен: {exc.message}")
        return me.username
    finally:
        await bot.session.close()


async def nft_check(url: str) -> None:
    async with aiohttp.ClientSession() as session:
        metadata = await NFTResolver(session).resolve(url)
    print(
        f"[OK] NFT: {metadata.title} | owner={metadata.owner_label or '—'} "
        f"| image={'да' if metadata.image_url else 'нет'}"
    )


async def run() -> int:
    parser = argparse.ArgumentParser(description="Проверка настройки NFT-бота")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="не обращаться к Telegram API",
    )
    parser.add_argument(
        "--nft",
        metavar="URL",
        help="дополнительно проверить ссылку t.me/nft/...",
    )
    args = parser.parse_args()

    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(f"[FAIL] Конфигурация: {exc}")
        return 2

    print("[OK] .env прочитан, BOT_TOKEN задан (значение не выводится)")
    print(f"[INFO] База: {settings.database_path}")
    print(
        f"[INFO] Оплата Stars: {'включена' if settings.payments_available else 'выключена'}; "
        f"админов: {len(settings.admin_ids)}; "
        f"OWNER: {', '.join(str(i) for i in sorted(settings.owner_ids)) or 'не задан'}"
    )
    print(
        f"[INFO] Срок предложения: {settings.offer_ttl_seconds // 3600} ч; "
        f"счёт: {settings.payment_window_seconds // 60} мин"
    )

    local_checks()
    role_checks()
    await database_check()

    if not args.offline:
        username = await telegram_check(settings)
        if username is None:
            return 3
    else:
        print("[SKIP] Telegram API: офлайн-режим")

    if args.nft:
        try:
            await nft_check(args.nft)
        except Exception as exc:
            print(f"[FAIL] NFT: {exc}")
            return 4

    print("[DONE] Проверка завершена")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
