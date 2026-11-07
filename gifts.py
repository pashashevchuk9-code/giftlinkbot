from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import OwnedGiftUnique, OwnedGifts

from database import Database

logger = logging.getLogger(__name__)


class GiftError(RuntimeError):
    pass


class GiftOwnershipError(GiftError):
    pass


class GiftNotTransferable(GiftError):
    pass


class GiftTransferError(GiftError):
    pass


@dataclass(frozen=True, slots=True)
class GiftProof:
    slug: str
    title: str
    owned_gift_id: str | None
    business_connection_id: str | None
    transfer_star_count: int
    can_auto_transfer: bool
    is_from_blockchain: bool

    @property
    def transfer_mode(self) -> str:
        return "business" if self.can_auto_transfer else "manual"


class GiftService:
    def __init__(self, bot: Bot, db: Database) -> None:
        self.bot = bot
        self.db = db

    async def _iter_gifts(
        self,
        fetch,
        *,
        user_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> list:
        result = []
        offset = ""
        for _ in range(10):
            kwargs = {
                "exclude_unlimited": True,
                "exclude_limited_upgradable": True,
                "exclude_limited_non_upgradable": True,
                "exclude_unique": False,
                "limit": 100,
                "offset": offset,
            }
            if user_id is not None:
                page: OwnedGifts = await fetch(user_id=user_id, **kwargs)
            else:
                page = await fetch(business_connection_id=business_connection_id, **kwargs)
            result.extend(page.gifts or [])
            if not page.next_offset:
                break
            offset = page.next_offset
        return result

    @staticmethod
    def _slug_key(value: str) -> str:
        """Приводит t.me/nft-ссылку и имя подарка к одному виду.

        Ссылка выглядит как ``PlushPepe-1``, а Telegram отдаёт имя
        ``Plush Pepe #1``. Поэтому сравниваем только буквы и цифры.
        """
        return re.sub(r"[^a-z0-9]+", "", value.casefold())

    @classmethod
    def _find_unique(cls, gifts: list, slug: str) -> OwnedGiftUnique | None:
        wanted = cls._slug_key(slug)
        if not wanted:
            return None
        for item in gifts:
            if not isinstance(item, OwnedGiftUnique):
                continue
            gift = item.gift
            candidates = {
                cls._slug_key(gift.name),
                cls._slug_key(gift.base_name) + str(gift.number),
            }
            if wanted in candidates:
                return item
        return None

    @staticmethod
    def _validate_gift(gift: OwnedGiftUnique) -> tuple[str, int, bool]:
        if gift.gift.is_from_blockchain:
            raise GiftNotTransferable(
                "Этот NFT пришёл из TON-блокчейна. Telegram Bot API не может "
                "передать его внутри Telegram; нужна сделка через TON-кошелёк."
            )
        if gift.gift.is_burned:
            raise GiftNotTransferable("NFT сожжён и больше не может быть передан.")
        if gift.can_be_transferred is False:
            raise GiftNotTransferable("Этот NFT сейчас нельзя передать другому владельцу.")
        next_date = gift.next_transfer_date
        if next_date is not None:
            if next_date.tzinfo is None:
                next_date = next_date.replace(tzinfo=timezone.utc)
            if next_date > datetime.now(timezone.utc):
                raise GiftNotTransferable(
                    "Передача NFT станет доступна позже: "
                    f"{next_date.astimezone().strftime('%d.%m.%Y %H:%M')}."
                )
        return gift.gift.base_name, int(gift.transfer_star_count or 0), bool(gift.gift.is_from_blockchain)

    async def verify_owner(self, user_id: int, slug: str) -> GiftProof:
        biz: dict | None = await self.db.get_business_connection(user_id)
        business_gift: OwnedGiftUnique | None = None
        business_id: str | None = None

        if biz and biz.get("is_enabled"):
            rights = biz.get("rights") or {}
            if rights.get("can_view_gifts_and_stars"):
                business_id = biz["connection_id"]
                try:
                    items = await self._iter_gifts(
                        self.bot.get_business_account_gifts,
                        business_connection_id=business_id,
                    )
                    business_gift = self._find_unique(items, slug)
                except TelegramAPIError as exc:
                    logger.warning(
                        "Не удалось получить подарки бизнес-аккаунта %s: %s",
                        user_id,
                        exc.message,
                    )

        if business_gift is not None:
            base_name, fee, from_chain = self._validate_gift(business_gift)
            rights = (biz or {}).get("rights") or {}
            can_auto = bool(
                business_id
                and rights.get("can_transfer_and_upgrade_gifts")
                and business_gift.owned_gift_id
                and (fee <= 0 or rights.get("can_transfer_stars"))
            )
            return GiftProof(
                slug=slug,
                title=base_name,
                owned_gift_id=business_gift.owned_gift_id,
                business_connection_id=business_id,
                transfer_star_count=fee,
                can_auto_transfer=can_auto,
                is_from_blockchain=from_chain,
            )

        try:
            items = await self._iter_gifts(
                self.bot.get_user_gifts,
                user_id=user_id,
            )
        except TelegramAPIError as exc:
            logger.warning("Не удалось получить подарки пользователя %s: %s", user_id, exc.message)
            raise GiftOwnershipError(
                "Не удалось проверить владение NFT. Нажмите /start в личном чате "
                "с ботом и попробуйте снова."
            ) from exc

        personal_gift = self._find_unique(items, slug)
        if personal_gift is None:
            raise GiftOwnershipError(
                "NFT с таким именем не найден среди ваших подарков. "
                "Проверьте ссылку и что NFT находится на вашем аккаунте."
            )

        base_name, fee, from_chain = self._validate_gift(personal_gift)
        return GiftProof(
            slug=slug,
            title=base_name,
            owned_gift_id=personal_gift.owned_gift_id,
            business_connection_id=None,
            transfer_star_count=fee,
            can_auto_transfer=False,
            is_from_blockchain=from_chain,
        )

    async def transfer_to_buyer(
        self,
        *,
        seller_id: int,
        buyer_id: int,
        proof: GiftProof,
    ) -> str:
        if not proof.can_auto_transfer or not proof.business_connection_id or not proof.owned_gift_id:
            raise GiftTransferError(
                "Автоматическая передача недоступна. Передайте NFT вручную."
            )

        connection = await self.db.get_business_connection(seller_id)
        if not connection or not connection.get("is_enabled"):
            raise GiftTransferError(
                "Telegram Business отключён. Передайте NFT вручную."
            )
        rights = connection.get("rights") or {}
        if not rights.get("can_transfer_and_upgrade_gifts"):
            raise GiftTransferError(
                "У бота нет права передачи подарков в Telegram Business. "
                "Передайте NFT вручную или выдайте право."
            )
        if proof.transfer_star_count > 0 and not rights.get("can_transfer_stars"):
            raise GiftTransferError(
                "Для передачи нужны Stars в бизнес-аккаунте и право "
                "can_transfer_stars. Передайте NFT вручную."
            )

        try:
            transferred = await self.bot.transfer_gift(
                business_connection_id=proof.business_connection_id,
                owned_gift_id=proof.owned_gift_id,
                new_owner_chat_id=buyer_id,
                star_count=proof.transfer_star_count if proof.transfer_star_count > 0 else None,
            )
        except TelegramAPIError as exc:
            raise GiftTransferError(
                f"Telegram не выполнил передачу NFT: {exc.message}"
            ) from exc

        if not transferred:
            raise GiftTransferError(
                "Telegram не подтвердил передачу NFT. Передайте NFT вручную."
            )
        return proof.owned_gift_id

    async def buyer_owns_gift(self, buyer_id: int, slug: str) -> bool:
        try:
            items = await self._iter_gifts(
                self.bot.get_user_gifts,
                user_id=buyer_id,
            )
        except TelegramAPIError:
            return False
        return self._find_unique(items, slug) is not None
