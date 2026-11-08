from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timezone
from sqlite3 import IntegrityError
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from aiogram.types import Chat, Message, User

from constants import OfferStatus, status_label
from database import Database
from gifts import GiftService
from keyboards import main_menu_keyboard, offer_main_keyboard
from nft import parse_nft_link
from parsing import OfferParseError, parse_offer_message
from roles import (
    Permission,
    Role,
    commands_for_role,
    has_permission,
    parse_role,
)

BOT = "GiftIinkBot"
CHAT = Chat(id=-100123, type="supergroup", title="Test")
BUYER = User(id=1, is_bot=False, first_name="Buyer", username="buyer")
SELLER = User(id=2, is_bot=False, first_name="Seller", username="seller")


def make_message(text: str, *, reply: Message | None = None) -> Message:
    return Message(
        message_id=10,
        date=datetime.now(timezone.utc),
        chat=CHAT,
        from_user=BUYER,
        text=text,
        reply_to_message=reply,
    )


def seller_message() -> Message:
    return Message(
        message_id=9,
        date=datetime.now(timezone.utc),
        chat=CHAT,
        from_user=SELLER,
        text="My NFT",
    )


class NLPLinkTests(unittest.TestCase):
    def test_parse_nft_link(self) -> None:
        self.assertEqual(parse_nft_link("https://t.me/nft/PlushPepe-1"), "PlushPepe-1")
        self.assertEqual(
            parse_nft_link("https://telegram.me/nft/ABC_1-2"), "ABC_1-2"
        )
        self.assertEqual(parse_nft_link("https://t.me/nft/123"), "123")
        self.assertIsNone(parse_nft_link("https://example.com/nft/1"))
        self.assertIsNone(parse_nft_link("https://t.me/nft/"))


class ParsingTests(unittest.TestCase):
    def test_reply_offer(self) -> None:
        request = parse_offer_message(
            make_message(
                "@GiftIinkBot https://t.me/nft/PlushPepe-1 100",
                reply=seller_message(),
            ),
            BOT,
            1,
            1_000_000,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.amount, 100)
        self.assertEqual(request.nft_slug, "PlushPepe-1")
        self.assertEqual(request.seller.user_id, SELLER.id)

    def test_explicit_seller(self) -> None:
        request = parse_offer_message(
            make_message(
                "@GiftIinkBot @seller https://t.me/nft/PlushPepe-1 100"
            ),
            BOT,
            1,
            1_000_000,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.seller.username, "seller")

    def test_offer_command(self) -> None:
        request = parse_offer_message(
            make_message(
                "/offer@GiftIinkBot https://t.me/nft/PlushPepe-1 100",
                reply=seller_message(),
            ),
            BOT,
            1,
            1_000_000,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.seller.user_id, SELLER.id)

    def test_not_addressed_to_bot(self) -> None:
        self.assertIsNone(
            parse_offer_message(make_message("hello"), BOT, 1, 1_000_000)
        )

    def test_missing_seller(self) -> None:
        with self.assertRaises(OfferParseError):
            parse_offer_message(
                make_message("@GiftIinkBot https://t.me/nft/PlushPepe-1 100"),
                BOT,
                1,
                1_000_000,
            )

    def test_missing_amount(self) -> None:
        with self.assertRaises(OfferParseError):
            parse_offer_message(
                make_message(
                    "@GiftIinkBot @seller https://t.me/nft/PlushPepe-1",
                    reply=None,
                ),
                BOT,
                1,
                1_000_000,
            )

    def test_two_numbers(self) -> None:
        with self.assertRaises(OfferParseError):
            parse_offer_message(
                make_message(
                    "@GiftIinkBot @seller https://t.me/nft/PlushPepe-1 100 200"
                ),
                BOT,
                1,
                1_000_000,
            )

    def test_self_offer(self) -> None:
        with self.assertRaises(OfferParseError):
            parse_offer_message(
                make_message(
                    "@GiftIinkBot @buyer https://t.me/nft/PlushPepe-1 100"
                ),
                BOT,
                1,
                1_000_000,
            )


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.sqlite3")
        await self.db.init()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self._tmp.cleanup()

    async def _create_offer(self, amount: int = 100) -> int:
        now = int(time.time())
        return await self.db.create_offer(
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
            nft_owner_label="Pavel Durov",
            amount=amount,
            expires_at=now + 3600,
        )

    async def test_full_happy_path(self) -> None:
        oid = await self._create_offer()
        now = int(time.time())
        self.assertTrue(
            await self.db.transition(oid, {"pending"}, "accepted", accepted_at=now)
        )
        self.assertTrue(
            await self.db.set_payment_pending(oid, "nonce", "https://t.me/$x", now + 60)
        )
        self.assertTrue(
            await self.db.mark_paid(oid, 1, 100, "nonce", "charge1", "prov1", 100)
        )
        self.assertTrue(await self.db.charge_exists("charge1"))
        self.assertFalse(
            await self.db.mark_paid(oid, 1, 100, "nonce", "charge1", "prov1", 100)
        )
        self.assertTrue(
            await self.db.mark_nft_transferred(oid, method="manual", verified=False)
        )
        self.assertTrue(await self.db.mark_payout_pending(oid))
        self.assertTrue(await self.db.mark_completed(oid, "tx123", 999))
        offer = await self.db.get_offer(oid)
        assert offer is not None
        self.assertEqual(offer["status"], OfferStatus.COMPLETED.value)
        self.assertEqual(offer["payout_reference"], "tx123")

    async def test_reject_is_atomic(self) -> None:
        oid = await self._create_offer()
        self.assertTrue(
            await self.db.transition(
                oid, {"pending"}, "rejected", closed_at=int(time.time())
            )
        )
        self.assertFalse(
            await self.db.transition(oid, {"pending"}, "accepted")
        )
        offer = await self.db.get_offer(oid)
        assert offer is not None
        self.assertEqual(offer["status"], OfferStatus.REJECTED.value)

    async def test_expiration(self) -> None:
        now = int(time.time())
        oid = await self._create_offer()
        await self.db.update_offer(oid, expires_at=now - 1)
        self.assertTrue(await self.db.mark_expired(oid))
        self.assertFalse(await self.db.mark_expired(oid))
        offer = await self.db.get_offer(oid)
        assert offer is not None
        self.assertEqual(offer["status"], OfferStatus.EXPIRED.value)

    async def test_one_active_deal_per_nft_and_seller(self) -> None:
        first = await self._create_offer()
        second = await self.db.create_offer(
            group_chat_id=-100123,
            buyer_id=3,
            buyer_username="buyer2",
            buyer_name="Buyer 2",
            seller_id=2,
            seller_username="seller",
            seller_name="Seller",
            nft_url="https://t.me/nft/PlushPepe-1",
            nft_slug="PlushPepe-1",
            nft_title="Plush Pepe #1",
            nft_image_url=None,
            nft_description=None,
            nft_owner_label=None,
            amount=200,
            expires_at=int(time.time()) + 3600,
        )
        self.assertTrue(
            await self.db.transition(
                first, {"pending"}, "accepted", accepted_at=int(time.time())
            )
        )
        conflict = await self.db.find_active_nft_offer(
            nft_slug="PlushPepe-1",
            seller_id=2,
            seller_username="seller",
            exclude_offer_id=second,
        )
        self.assertIsNotNone(conflict)
        assert conflict is not None
        self.assertEqual(conflict["id"], first)
        with self.assertRaises(IntegrityError):
            await self.db.transition(
                second, {"pending"}, "accepted", accepted_at=int(time.time())
            )

    async def test_refund_claim_is_idempotent(self) -> None:
        oid = await self._create_offer()
        self.assertTrue(
            await self.db.claim_refund(
                charge_id="charge1",
                offer_id=oid,
                user_id=1,
                amount=100,
                reason="test",
            )
        )
        self.assertFalse(
            await self.db.claim_refund(
                charge_id="charge1",
                offer_id=oid,
                user_id=1,
                amount=100,
                reason="again",
            )
        )
        await self.db.release_refund("charge1")
        self.assertTrue(
            await self.db.claim_refund(
                charge_id="charge1",
                offer_id=oid,
                user_id=1,
                amount=100,
                reason="retry",
            )
        )


class GiftMatchingTests(unittest.TestCase):
    def test_slug_matches_telegram_name(self) -> None:
        from aiogram.types import OwnedGiftUnique

        gift = SimpleNamespace(
            name="Plush Pepe #1",
            base_name="Plush Pepe",
            number=1,
        )
        item = OwnedGiftUnique.model_construct(
            type="unique",
            gift=gift,
            send_date=0,
            owned_gift_id="owned-1",
            can_be_transferred=True,
            transfer_star_count=0,
        )
        self.assertIs(GiftService._find_unique([item], "PlushPepe-1"), item)
        self.assertIsNone(GiftService._find_unique([item], "PlushPepe-11"))
        self.assertIs(GiftService._find_unique([item], "plush-pepe-1"), item)


class InterfaceTests(unittest.TestCase):
    def test_plain_buttons(self) -> None:
        keyboard = offer_main_keyboard(7)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(labels, ["Принять", "Отклонить"])

    def test_status_labels(self) -> None:
        self.assertEqual(status_label(OfferStatus.REJECTED.value), "Отклонена")
        self.assertEqual(status_label(OfferStatus.EXPIRED.value), "Истекло")
        self.assertEqual(status_label(OfferStatus.CANCELLED.value), "Отменена")

    def test_caption_lengths_and_footer(self) -> None:
        from deals import DealService

        settings = SimpleNamespace(
            offer_ttl_seconds=48 * 3600,
            tz=ZoneInfo("Europe/Moscow"),
        )
        service = DealService(
            bot=None,
            db=None,
            settings=settings,
            nft=None,
            gifts=None,
            bot_username=BOT,
        )
        now = int(time.time())
        base = {
            "id": 7,
            "nft_title": "Plush Pepe #1",
            "nft_url": "https://t.me/nft/PlushPepe-1",
            "amount": 100,
            "buyer_id": 1,
            "buyer_username": "buyer",
            "buyer_name": "Buyer",
            "seller_id": 2,
            "seller_username": "seller",
            "seller_name": "Seller",
            "expires_at": now + 48 * 3600,
            "nft_transfer_mode": "manual",
            "nft_transfer_star_count": 0,
        }
        for status in (item.value for item in OfferStatus):
            offer = {**base, "status": status}
            caption = service._caption(offer)
            self.assertLess(len(caption), 1024, status)
            if status == "pending":
                self.assertIn("@GiftIinkBot", caption)
        pending = service._caption({**base, "status": OfferStatus.PENDING.value})
        self.assertIn(
            "@buyer предлагает Вам 100 звёзд за подарок",
            pending,
        )
        self.assertIn("Plush Pepe #1", pending)
        self.assertIn("Предложение действует ещё 48ч 00м.", pending)

        near_end = service._caption(
            {
                **base,
                "status": OfferStatus.PENDING.value,
                "expires_at": now + 47 * 3600 + 59 * 60,
            }
        )
        self.assertIn("Предложение действует ещё 47ч 59м.", near_end)

        without_hash = {
            **base,
            "nft_title": "Plush Pepe",
            "nft_slug": "PlushPepe-12345",
        }
        self.assertIn("Plush Pepe #12345", service._nft_label(without_hash))

        accepted = service._accepted_details_text(
            {**base, "status": OfferStatus.ACCEPTED.value}
        )
        self.assertIn("Продавцу к выплате", accepted)
        self.assertIn("Подтвердить сделку", accepted)


class RolePermissionTests(unittest.TestCase):
    def test_exactly_seven_roles(self) -> None:
        self.assertEqual(len(list(Role)), 7)
        self.assertEqual(
            {role.value for role in Role},
            {"USER", "TECH ADMIN", "ADMIN", "OWNER", "SKAM", "WORKER", "IVAN"},
        )

    def test_role_matrix(self) -> None:
        self.assertTrue(has_permission(Role.USER, Permission.CREATE_OFFER))
        self.assertTrue(has_permission(Role.WORKER, Permission.CREATE_OFFER))
        self.assertFalse(has_permission(Role.WORKER, Permission.VIEW_STATS))

        self.assertTrue(has_permission(Role.TECH_ADMIN, Permission.BAN_USERS))
        self.assertFalse(has_permission(Role.TECH_ADMIN, Permission.BROADCAST))

        self.assertTrue(has_permission(Role.ADMIN, Permission.BROADCAST))
        self.assertFalse(has_permission(Role.ADMIN, Permission.BAN_USERS))
        self.assertFalse(has_permission(Role.ADMIN, Permission.MANAGE_ROLES))

        self.assertTrue(has_permission(Role.IVAN, Permission.VIEW_STATS))
        self.assertFalse(has_permission(Role.IVAN, Permission.BAN_USERS))
        self.assertFalse(has_permission(Role.IVAN, Permission.MANAGE_ROLES))
        self.assertFalse(
            has_permission(Role.IVAN, Permission.MANAGE_MAINTENANCE)
        )

        for permission in Permission:
            self.assertTrue(has_permission(Role.OWNER, permission))
            self.assertFalse(has_permission(Role.SKAM, permission))

    def test_parse_role_aliases(self) -> None:
        self.assertIs(parse_role("TECH_ADMIN"), Role.TECH_ADMIN)
        self.assertIs(parse_role("tech admin"), Role.TECH_ADMIN)
        self.assertIs(parse_role("Иван"), Role.IVAN)
        self.assertIs(parse_role("скам"), Role.SKAM)
        self.assertIsNone(parse_role("superuser"))


class MenuTests(unittest.TestCase):
    def test_main_menu_labels(self) -> None:
        keyboard = main_menu_keyboard()
        labels = [
            button.text
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertEqual(
            labels,
            [
                "Создать предложение",
                "Мои предложения",
                "История сделок",
                "Уведомления",
                "Правила обмена",
                "Поддержка",
                "Мой профиль",
            ],
        )

    def test_welcome_text(self) -> None:
        from menu_handlers import WELCOME_TEXT

        self.assertTrue(WELCOME_TEXT.startswith("👋 Добро пожаловать!"))
        self.assertIn("NFT & Stars Exchange", WELCOME_TEXT)
        self.assertIn("Выберите нужный раздел ниже", WELCOME_TEXT)

    def test_comand_lists(self) -> None:
        user_commands = {name for name, _ in commands_for_role(Role.USER)}
        self.assertIn("/start", user_commands)
        self.assertNotIn("/stats", user_commands)
        admin_commands = {name for name, _ in commands_for_role(Role.ADMIN)}
        self.assertIn("/stats", admin_commands)
        self.assertNotIn("/ban", admin_commands)
        tech_commands = {
            name for name, _ in commands_for_role(Role.TECH_ADMIN)
        }
        self.assertIn("/ban", tech_commands)
        self.assertNotIn("/broadcast", tech_commands)
        owner_commands = {name for name, _ in commands_for_role(Role.OWNER)}
        self.assertIn("/setrole", owner_commands)
        self.assertIn("/roles", owner_commands)
        self.assertIn("/zakrit", owner_commands)
        self.assertIn("/stats", owner_commands)
        self.assertNotIn("/roles", admin_commands)
        self.assertEqual(commands_for_role(Role.SKAM), [])


class RoleDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "roles.sqlite3")
        await self.db.init()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self._tmp.cleanup()

    async def test_new_user_is_user_and_owner_sync(self) -> None:
        record = await self.db.ensure_user(10, "new", "New", None)
        self.assertEqual(record["role"], Role.USER.value)
        self.assertIsNotNone(record["registered_at"])

        owner = await self.db.ensure_user(
            11, "owner", "Owner", None, owner_ids=frozenset({11})
        )
        self.assertEqual(owner["role"], Role.OWNER.value)

        # OWNER определяется только ID из конфигурации.
        downgraded = await self.db.ensure_user(11, "owner", "Owner", None)
        self.assertEqual(downgraded["role"], Role.USER.value)

    async def test_roles_bans_warnings_restrictions(self) -> None:
        await self.db.ensure_user(20, "target", "Target", None)
        self.assertTrue(await self.db.set_user_role(20, Role.ADMIN))
        self.assertEqual(
            (await self.db.get_user(20))["role"], Role.ADMIN.value
        )

        await self.db.set_ban(20, banned=True, admin_id=1, reason="spam")
        record = await self.db.get_user(20)
        self.assertEqual(record["is_banned"], 1)
        self.assertEqual(record["ban_reason"], "spam")

        await self.db.set_ban(20, banned=False, admin_id=1)
        self.assertEqual((await self.db.get_user(20))["is_banned"], 0)

        await self.db.add_warning(20, 1, "first")
        await self.db.add_warning(20, 1, "second")
        self.assertEqual(await self.db.count_warnings(20), 2)

        until = int(time.time()) + 3600
        await self.db.set_restriction(20, until=until, reason="timeout")
        self.assertEqual(
            (await self.db.get_user(20))["restriction_until"], until
        )

    async def test_maintenance_survives_and_expires(self) -> None:
        await self.db.set_maintenance(until=None, admin_id=1)
        active, until = await self.db.maintenance_state()
        self.assertTrue(active)
        self.assertIsNone(until)

        await self.db.clear_maintenance()
        self.assertFalse((await self.db.maintenance_state())[0])

        await self.db.set_maintenance(until=int(time.time()) - 1, admin_id=1)
        self.assertFalse((await self.db.maintenance_state())[0])

    async def test_admin_log_notifications_and_backup(self) -> None:
        await self.db.ensure_user(30, "user", "User", None)
        await self.db.log_admin_action(1, "setrole", 30, {"role": "ADMIN"})
        log = await self.db.list_admin_log(5)
        self.assertEqual(log[0]["action"], "setrole")
        self.assertEqual(log[0]["target_id"], 30)

        await self.db.add_notification(30, "hello")
        items = await self.db.list_notifications(30, 5)
        self.assertEqual(items[0]["text"], "hello")
        self.assertTrue(await self.db.notifications_enabled(30))
        await self.db.set_notifications_enabled(30, False)
        self.assertFalse(await self.db.notifications_enabled(30))

        backup = Path(self._tmp.name) / "backup.sqlite3"
        await self.db.backup_to(backup)
        self.assertTrue(backup.exists())
        self.assertGreater(backup.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
