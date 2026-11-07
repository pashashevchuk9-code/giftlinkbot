from __future__ import annotations

import html
import logging
import re
import secrets
import time
from datetime import datetime
from sqlite3 import IntegrityError
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    User,
)

from config import Settings
from constants import OfferStatus, status_label
from database import Database
from gifts import GiftError, GiftService
from keyboards import (
    buyer_confirm_keyboard,
    offer_details_keyboard,
    offer_main_keyboard,
    payment_keyboard,
    seller_paid_keyboard,
)
from nft import NFTLookupError, NFTResolver
from parsing import OfferParseError, parse_offer_message
from access import (
    BANNED_TEXT,
    MAINTENANCE_TEXT,
    SKAM_ALERT_TEXT,
    access_block_reason,
)
from roles import PAYMENT_ADMIN_ROLES, Role, is_staff, role_from_db

logger = logging.getLogger(__name__)


def _now() -> int:
    return int(time.time())


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


class DealService:
    def __init__(
        self,
        *,
        bot: Bot,
        db: Database,
        settings: Settings,
        nft: NFTResolver,
        gifts: GiftService,
        bot_username: str,
    ) -> None:
        self.bot = bot
        self.db = db
        self.settings = settings
        self.nft = nft
        self.gifts = gifts
        self.bot_username = bot_username
        self._last_card_caption: dict[int, str] = {}

    # ---------------------------------------------------------------- access

    async def role_for(self, user_id: int) -> Role:
        record = await self.db.get_user(user_id)
        if record is None:
            return Role.USER
        return role_from_db(record.get("role"))

    async def is_payment_admin(self, user_id: int) -> bool:
        if user_id in getattr(self.settings, "owner_ids", frozenset()):
            return True
        if user_id in self.settings.admin_ids:
            return True
        return await self.role_for(user_id) in PAYMENT_ADMIN_ROLES

    async def access_error_for(self, user_id: int) -> str | None:
        """Серверная проверка перед любым пользовательским действием."""
        role = await self.role_for(user_id)
        return await access_block_reason(self.db, self.settings, user_id, role)

    async def effective_min_stars(self) -> int:
        raw = await self.db.setting_get(
            "min_offer_stars", str(self.settings.min_offer_stars)
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return self.settings.min_offer_stars

    async def effective_max_stars(self) -> int:
        raw = await self.db.setting_get(
            "max_offer_stars", str(self.settings.max_offer_stars)
        )
        try:
            return max(await self.effective_min_stars(), int(raw))
        except (TypeError, ValueError):
            return self.settings.max_offer_stars

    # ------------------------------------------------------------------ utils

    def _fmt_dt(self, timestamp: int | None) -> str:
        if not timestamp:
            return "—"
        dt = datetime.fromtimestamp(timestamp, tz=self.settings.tz)
        return dt.strftime("%d.%m.%Y %H:%M")

    def _buyer_label(self, offer: dict[str, Any]) -> str:
        username = offer.get("buyer_username")
        if username:
            return f"@{_esc(username)}"
        name = _esc(offer.get("buyer_name") or "Покупатель")
        return f'<a href="tg://user?id={offer["buyer_id"]}">{name}</a>'

    def _seller_label(self, offer: dict[str, Any]) -> str:
        username = offer.get("seller_username")
        if username:
            return f"@{_esc(username)}"
        if offer.get("seller_id"):
            name = _esc(offer.get("seller_name") or "Продавец")
            return f'<a href="tg://user?id={offer["seller_id"]}">{name}</a>'
        return "продавец"

    def _nft_link(self, offer: dict[str, Any]) -> str:
        url = _esc(offer["nft_url"])
        return f'<a href="{url}">{url}</a>'

    def _footer(self, label: str = "Предложение") -> str:
        return (
            f"<i>{label} бота @{_esc(self.bot_username)}. "
            "Не системное уведомление Telegram.</i>"
        )

    def _short_title(self, title: str, limit: int = 70) -> str:
        return title if len(title) <= limit else title[: limit - 1] + "…"

    @staticmethod
    def _stars_label(amount: int) -> str:
        amount = int(amount)
        if amount % 10 == 1 and amount % 100 != 11:
            word = "звезда"
        elif amount % 10 in {2, 3, 4} and amount % 100 not in {12, 13, 14}:
            word = "звезды"
        else:
            word = "звёзд"
        return f"{amount} {word}"

    def _nft_label(self, offer: dict[str, Any]) -> str:
        """Название и номер NFT из ссылки, с сохранением кликабельной ссылки."""
        title = str(offer.get("nft_title") or "").strip()
        slug = str(offer.get("nft_slug") or "").strip()
        number: str | None = None
        name = title

        match = re.search(r"#\s*(\d+)", title)
        if match:
            number = match.group(1)
            name = title[: match.start()].strip()
        else:
            match = re.search(r"-(\d+)$", slug)
            if match:
                number = match.group(1)

        if not name:
            name = re.sub(r"-\d+$", "", slug).strip() or "NFT"
        if not title and name == slug:
            name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)

        visible = f"{name} #{number}" if number else name
        url = _esc(offer["nft_url"])
        return f'<a href="{url}">{_esc(visible)}</a>'

    @staticmethod
    def _remaining_label(expires_at: int) -> str:
        remaining = max(0, int(expires_at) - _now())
        total_minutes = (remaining + 59) // 60
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}ч {minutes:02d}м"

    # ---------------------------------------------------------------- captions

    def _caption(self, offer: dict[str, Any]) -> str:
        status = offer["status"]
        title = _esc(self._short_title(offer["nft_title"]))
        link = self._nft_link(offer)
        amount = int(offer["amount"])
        buyer = self._buyer_label(offer)
        seller = self._seller_label(offer)
        oid = offer["id"]

        lines = [f"<b>{title}</b>", link, ""]

        if status == OfferStatus.PENDING.value:
            return (
                f"{buyer} предлагает Вам {self._stars_label(amount)} "
                f"за подарок {self._nft_label(offer)}.\n"
                f"Предложение действует ещё "
                f"{self._remaining_label(offer['expires_at'])}.\n\n"
                f"{self._footer('Предложение')}"
            )

        if status == OfferStatus.ACCEPTED.value:
            transfer = (
                "автоматически через Telegram Business"
                if offer.get("nft_transfer_mode") == "business"
                else "вручную продавцом"
            )
            fee = int(offer.get("nft_transfer_star_count") or 0)
            lines.extend(
                [
                    f"Сделка №{oid}. Продавец принял предложение.",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                    f"Передача NFT: {transfer}",
                ]
            )
            if fee > 0:
                lines.append(
                    f"Комиссия Telegram за передачу: <b>{fee} Stars</b> "
                    "с бизнес-аккаунта продавца."
                )
            lines.extend(
                [
                    "",
                    f"Продавцу к выплате: <b>{amount} Stars</b>",
                    "Подтвердите сделку, чтобы покупатель получил счёт.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.AWAITING_PAYMENT.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Ожидает оплаты</b>",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                    f"Счёт действует до {self._fmt_dt(offer.get('payment_due_at'))}",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.PAID.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Оплачено</b>",
                    f"Получено: <b>{int(offer.get('paid_amount') or amount)} Stars</b>",
                    f"Покупатель: {buyer}",
                    "Ожидает передачи NFT. Продавец получил инструкцию.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.TRANSFERRING.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Передача NFT</b>",
                    f"Покупатель: {buyer}",
                    "Бот выполняет передачу через Telegram Business.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.NFT_TRANSFERRED.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>NFT передан</b>",
                    f"Покупатель: {buyer}",
                    "Ожидает подтверждения получения покупателем.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.PAYOUT_PENDING.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Получение подтверждено</b>",
                    f"Покупатель: {buyer}",
                    f"Продавцу к выплате: <b>{amount} Stars</b>",
                    "Выплата выполняется оператором вручную.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.COMPLETED.value:
            ref = offer.get("payout_reference")
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Завершена</b>",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                ]
            )
            if ref:
                lines.append(f"Выплата оператора: <code>{_esc(ref)}</code>")
            lines.append(self._footer("Сделка"))
            return "\n".join(lines)

        if status == OfferStatus.DISPUTED.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Открыт спор</b>",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                    "Оператор получил уведомление и разберётся.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.REFUNDED.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Возврат выполнен</b>",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                    "Telegram подтвердил возврат покупателю.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.REJECTED.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Отклонена</b>",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                    "Повторное выполнение невозможно.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.EXPIRED.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Истекло</b>",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                    f"Срок истёк {self._fmt_dt(offer.get('expires_at'))}.",
                    "Кнопки больше не работают.",
                    self._footer("Сделка"),
                ]
            )
            return "\n".join(lines)

        if status == OfferStatus.CANCELLED.value:
            lines.extend(
                [
                    f"Сделка №{oid}. <b>Отменена</b>",
                    f"Покупатель: {buyer}",
                    f"Сумма: <b>{amount} Stars</b>",
                ]
            )
            reason = offer.get("cancel_reason")
            if reason:
                lines.append(f"Причина: {_esc(reason)}")
            lines.append(self._footer("Сделка"))
            return "\n".join(lines)

        lines.extend(
            [
                f"Сделка №{oid}. <b>{_esc(status_label(status))}</b>",
                f"Покупатель: {buyer}",
                f"Сумма: <b>{amount} Stars</b>",
                self._footer("Сделка"),
            ]
        )
        return "\n".join(lines)

    def _accepted_details_text(self, offer: dict[str, Any]) -> str:
        amount = int(offer["amount"])
        fee = int(offer.get("nft_transfer_star_count") or 0)
        transfer = (
            "автоматически через Telegram Business"
            if offer.get("nft_transfer_mode") == "business"
            else "вручную продавцом"
        )
        lines = [
            f"<b>Сделка №{offer['id']}: подтверждение</b>",
            f"NFT: <b>{_esc(self._short_title(offer['nft_title']))}</b>",
            f"Ссылка: {self._nft_link(offer)}",
            f"Покупатель: {self._buyer_label(offer)}",
            f"Продавцу к выплате: <b>{amount} Stars</b>",
            f"Передача NFT: {transfer}",
        ]
        if fee > 0:
            lines.append(
                f"Комиссия Telegram за передачу: <b>{fee} Stars</b> "
                "с бизнес-аккаунта продавца."
            )
        lines.extend(
            [
                "",
                "<b>Что дальше</b>",
                "1. Нажмите «Подтвердить сделку».",
                "2. Покупатель получит официальный счёт Telegram Stars.",
                "3. После оплаты передайте NFT покупателю.",
                "4. Покупатель подтвердит получение, и оператор выплатит вам Stars.",
                "",
                self._footer("Сделка"),
            ]
        )
        return "\n".join(lines)

    def _keyboard(self, offer: dict[str, Any]):
        status = offer["status"]
        if status == OfferStatus.PENDING.value:
            return offer_main_keyboard(offer["id"])
        if status == OfferStatus.ACCEPTED.value:
            return offer_details_keyboard(offer["id"])
        return None

    # ------------------------------------------------------------- card output

    async def send_offer_card(self, offer: dict[str, Any]) -> Message:
        chat_id = offer["group_chat_id"]
        caption = self._caption(offer)
        keyboard = self._keyboard(offer)
        image_url = offer.get("nft_image_url")
        message: Message | None = None

        if image_url:
            try:
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                await self.db.set_group_message(offer["id"], message.message_id, "photo")
                self._last_card_caption[offer["id"]] = caption
                return message
            except TelegramAPIError as exc:
                logger.warning("Не удалось отправить фото NFT, отправляю текст: %s", exc.message)

        message = await self.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            link_preview_options={"is_disabled": True},
        )
        await self.db.set_group_message(offer["id"], message.message_id, "text")
        self._last_card_caption[offer["id"]] = caption
        return message

    async def _refresh_card(self, offer_id: int) -> dict[str, Any] | None:
        offer = await self.db.get_offer(offer_id)
        if offer is None or not offer.get("group_message_id"):
            return offer
        caption = self._caption(offer)
        keyboard = self._keyboard(offer)
        try:
            if offer.get("card_kind") == "photo":
                await self.bot.edit_message_caption(
                    chat_id=offer["group_chat_id"],
                    message_id=offer["group_message_id"],
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            else:
                await self.bot.edit_message_text(
                    chat_id=offer["group_chat_id"],
                    message_id=offer["group_message_id"],
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    link_preview_options={"is_disabled": True},
                )
        except TelegramBadRequest as exc:
            text = (exc.message or "").lower()
            if "message is not modified" not in text:
                logger.warning("Не удалось обновить карточку #%s: %s", offer_id, exc.message)
        except TelegramAPIError as exc:
            logger.warning("Не удалось обновить карточку #%s: %s", offer_id, exc.message)
        self._last_card_caption[offer_id] = caption
        return offer

    async def _notify_user(
        self,
        user_id: int,
        text: str,
        *,
        keyboard=None,
    ) -> bool:
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                link_preview_options={"is_disabled": True},
            )
        except TelegramAPIError:
            return False
        try:
            await self.db.add_notification(user_id, text)
        except Exception:
            logger.debug("Не удалось сохранить уведомление", exc_info=True)
        return True

    async def _notify_group(
        self,
        offer: dict[str, Any],
        text: str,
        *,
        keyboard=None,
    ) -> None:
        try:
            await self.bot.send_message(
                chat_id=offer["group_chat_id"],
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                link_preview_options={"is_disabled": True},
            )
        except TelegramAPIError as exc:
            logger.warning("Не удалось отправить сообщение в группу: %s", exc.message)

    async def _user_or_group(
        self,
        offer: dict[str, Any],
        user_id: int,
        text: str,
        *,
        keyboard=None,
        group_text: str | None = None,
    ) -> None:
        if await self._notify_user(user_id, text, keyboard=keyboard):
            return
        if group_text:
            await self._notify_group(offer, group_text, keyboard=keyboard)

    async def _callback_alert(self, callback: CallbackQuery, text: str) -> None:
        try:
            await callback.answer(text[:200], show_alert=True)
        except TelegramAPIError:
            pass

    async def _guard_callback(self, callback: CallbackQuery) -> bool:
        blocked = await self.access_error_for(callback.from_user.id)
        if blocked:
            await self._callback_alert(callback, blocked)
            return False
        return True

    async def _callback_done(self, callback: CallbackQuery, text: str = "Готово") -> None:
        try:
            await callback.answer(text[:200])
        except TelegramAPIError:
            pass

    # --------------------------------------------------------------- creating

    async def parse_and_create(self, message: Message) -> bool:
        if message.chat.type not in {ChatType.GROUP.value, ChatType.SUPERGROUP.value}:
            return False
        if not message.from_user or message.from_user.is_bot:
            return False
        if message.sender_chat is not None:
            await message.reply(
                "Анонимные сообщения от имени канала не могут создавать сделки. "
                "Отправьте команду от личного аккаунта."
            )
            return True

        try:
            request = parse_offer_message(
                message,
                self.bot_username,
                await self.effective_min_stars(),
                await self.effective_max_stars(),
            )
        except OfferParseError as exc:
            await message.reply(str(exc))
            return True

        if request is None:
            return False

        blocked = await self.access_error_for(message.from_user.id)
        if blocked:
            await message.reply(blocked)
            return True

        await self.db.upsert_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )

        existing = await self.db.find_active_offer(
            buyer_id=message.from_user.id,
            nft_slug=request.nft_slug,
            seller_id=request.seller.user_id,
            seller_username=request.seller.username,
        )
        if (
            existing
            and existing["status"] == OfferStatus.PENDING.value
            and existing["expires_at"] <= _now()
        ):
            await self.db.mark_expired(existing["id"])
            await self._refresh_card(existing["id"])
            existing = None
        if existing:
            await message.reply(
                f"По этому NFT уже есть активное предложение №{existing['id']} "
                f"в статусе «{status_label(existing['status'])}»."
            )
            return True

        try:
            metadata = await self.nft.resolve(request.nft_url)
        except NFTLookupError as exc:
            await message.reply(str(exc))
            return True

        if request.seller.user_id is not None:
            await self.db.upsert_user(
                request.seller.user_id,
                request.seller.username,
                request.seller.display_name,
                None,
            )

        now = _now()
        offer_id = await self.db.create_offer(
            group_chat_id=message.chat.id,
            buyer_id=message.from_user.id,
            buyer_username=message.from_user.username,
            buyer_name=" ".join(
                part for part in (message.from_user.first_name, message.from_user.last_name) if part
            )
            or f"id{message.from_user.id}",
            seller_id=request.seller.user_id,
            seller_username=request.seller.username,
            seller_name=request.seller.display_name,
            nft_url=metadata.url,
            nft_slug=metadata.slug,
            nft_title=metadata.title,
            nft_image_url=metadata.image_url,
            nft_description=metadata.description,
            nft_owner_label=metadata.owner_label,
            amount=request.amount,
            expires_at=now + self.settings.offer_ttl_seconds,
        )
        await self.db.add_event(
            offer_id,
            message.from_user.id,
            "offer_created",
            {
                "amount": request.amount,
                "slug": metadata.slug,
                "seller_id": request.seller.user_id,
                "seller_username": request.seller.username,
            },
        )
        offer = await self.db.get_offer(offer_id)
        assert offer is not None
        try:
            await self.send_offer_card(offer)
        except TelegramAPIError as exc:
            logger.exception("Не удалось отправить карточку предложения #%s: %s", offer_id, exc.message)
            await self.db.transition(
                offer_id,
                {OfferStatus.PENDING.value},
                OfferStatus.FAILED.value,
                cancel_reason="Не удалось отправить карточку",
                closed_at=_now(),
            )
            await message.reply(
                "Не удалось отправить карточку предложения. "
                "Проверьте права бота в группе."
            )
        else:
            seller_id = request.seller.user_id
            if seller_id and await self.db.notifications_enabled(seller_id):
                await self._notify_user(
                    seller_id,
                    f"Вам предложили обмен по NFT "
                    f"{self._nft_label(offer)}.\n"
                    f"Сумма: <b>{request.amount} Stars</b>.\n"
                    f"Откройте карточку в группе, чтобы принять или отклонить.",
                )
        return True

    # --------------------------------------------------------------- commands

    async def cancel_by_command(self, offer_id: int, user: User) -> str:
        offer = await self.db.get_offer(offer_id)
        if offer is None:
            return "Сделка не найдена."
        is_buyer = offer["buyer_id"] == user.id
        is_seller = (
            offer.get("seller_id") == user.id
            or (
                offer.get("seller_id") is None
                and offer.get("seller_username")
                and user.username
                and offer["seller_username"].lower() == user.username.lower()
            )
        )
        is_admin = await self.is_payment_admin(user.id)
        if not (is_buyer or is_seller or is_admin):
            return "У вас нет доступа к этой сделке."
        if offer["status"] not in {
            OfferStatus.PENDING.value,
            OfferStatus.ACCEPTED.value,
            OfferStatus.AWAITING_PAYMENT.value,
        }:
            return f"Сделку нельзя отменить из статуса «{status_label(offer['status'])}»."
        if offer.get("paid_at"):
            return "Покупатель уже оплатил. Для возврата нужен оператор: /refund " + str(offer_id)
        if offer["status"] == OfferStatus.PENDING.value and offer["expires_at"] <= _now():
            await self.db.mark_expired(offer_id)
            await self._refresh_card(offer_id)
            return "Срок действия предложения уже истёк."

        ok = await self.db.mark_cancelled(
            offer_id,
            {
                OfferStatus.PENDING.value,
                OfferStatus.ACCEPTED.value,
                OfferStatus.AWAITING_PAYMENT.value,
            },
            "Отменена пользователем",
        )
        if not ok:
            return "Статус сделки уже изменился. Обновите карточку."
        await self.db.add_event(offer_id, user.id, "cancelled", {"by": user.id})
        await self._refresh_card(offer_id)
        seller_id = offer.get("seller_id")
        if is_buyer:
            if seller_id:
                await self._notify_user(
                    seller_id,
                    f"Сделка №{offer_id} отменена покупателем.",
                )
        else:
            await self._notify_user(
                offer["buyer_id"],
                f"Сделка №{offer_id} отменена продавцом.",
            )
            if is_admin and seller_id and seller_id != user.id:
                await self._notify_user(
                    seller_id,
                    f"Сделка №{offer_id} отменена оператором.",
                )
        return f"Сделка №{offer_id} отменена."

    # ------------------------------------------------------------- callbacks

    async def on_accept(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        if callback.message is None or callback.message.chat.id != offer["group_chat_id"]:
            await self._callback_alert(callback, "Кнопка не относится к этому чату.")
            return

        user = callback.from_user
        if not self._is_seller(offer, user):
            await self._callback_alert(callback, "Это предложение не для вас.")
            return
        if offer["status"] != OfferStatus.PENDING.value:
            await self._callback_alert(
                callback, f"Статус сделки: {status_label(offer['status'])}."
            )
            return
        if offer["expires_at"] <= _now():
            await self.db.mark_expired(offer["id"])
            await self._refresh_card(offer["id"])
            await self._callback_alert(callback, "Срок действия предложения истёк.")
            return

        conflict = await self.db.find_active_nft_offer(
            nft_slug=offer["nft_slug"],
            seller_id=user.id,
            seller_username=user.username,
            exclude_offer_id=offer["id"],
        )
        if conflict:
            await self._callback_alert(
                callback,
                f"По этому NFT уже идёт сделка №{conflict['id']} "
                f"в статусе «{status_label(conflict['status'])}». "
                "Дождитесь её завершения.",
            )
            return

        await self._bind_seller_if_needed(offer, user)
        offer = await self.db.get_offer(offer["id"])
        assert offer is not None

        await self._callback_done(callback, "Проверяю NFT…")
        try:
            proof = await self.gifts.verify_owner(user.id, offer["nft_slug"])
        except GiftError as exc:
            await self._user_or_group(
                offer,
                user.id,
                f"Не удалось принять предложение: {_esc(str(exc))}",
                group_text=f"{self._seller_label(offer)}, не удалось принять предложение: {_esc(str(exc))}",
            )
            return

        try:
            ok = await self.db.transition(
                offer["id"],
                {OfferStatus.PENDING.value},
                OfferStatus.ACCEPTED.value,
                require_unexpired=True,
                accepted_at=_now(),
                seller_id=user.id,
                seller_username=user.username,
                seller_name=" ".join(p for p in (user.first_name, user.last_name) if p),
                nft_owned_gift_id=proof.owned_gift_id,
                nft_business_connection_id=proof.business_connection_id,
                nft_transfer_mode=proof.transfer_mode,
                nft_transfer_star_count=proof.transfer_star_count,
            )
        except IntegrityError:
            ok = False
        if not ok:
            await self._notify_user(
                user.id,
                "Предложение уже изменилось. Обновите карточку в группе.",
            )
            return

        await self.db.add_event(
            offer["id"],
            user.id,
            "accepted",
            {
                "transfer_mode": proof.transfer_mode,
                "transfer_star_count": proof.transfer_star_count,
            },
        )
        await self._refresh_card(offer["id"])
        await self._user_or_group(
            offer,
            offer["buyer_id"],
            f"Продавец принял предложение №{offer['id']}. "
            "Он подтвердит сделку, после чего вы получите счёт на оплату.",
            group_text=f"{self._buyer_label(offer)}, продавец принял предложение №{offer['id']}.",
        )

        fresh = await self.db.get_offer(offer["id"])
        assert fresh is not None
        details = self._accepted_details_text(fresh)
        details_keyboard = offer_details_keyboard(offer["id"])
        sent = await self._notify_user(
            user.id,
            details,
            keyboard=details_keyboard,
        )
        if not sent:
            await self._notify_group(
                fresh,
                f"{self._seller_label(fresh)}, {details}",
                keyboard=details_keyboard,
            )

    async def on_confirm(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        user = callback.from_user
        if not self._is_seller(offer, user):
            await self._callback_alert(callback, "Это предложение не для вас.")
            return
        if offer["status"] != OfferStatus.ACCEPTED.value:
            await self._callback_alert(
                callback, f"Статус сделки: {status_label(offer['status'])}."
            )
            return
        if not self.settings.payments_available:
            await self._callback_alert(
                callback,
                "Оплата Stars отключена. Настройте ADMIN_IDS, PAYMENTS_ENABLED "
                "и OPERATOR_PAYOUT_ACK в .env.",
            )
            return

        await self._callback_done(callback, "Проверяю NFT…")
        try:
            proof = await self.gifts.verify_owner(user.id, offer["nft_slug"])
        except GiftError as exc:
            await self._user_or_group(
                offer,
                user.id,
                f"Не удалось подтвердить сделку: {_esc(str(exc))}",
                group_text=f"{self._seller_label(offer)}, не удалось подтвердить сделку: {_esc(str(exc))}",
            )
            return

        nonce = secrets.token_urlsafe(24)
        payment_due_at = _now() + self.settings.payment_window_seconds
        title = f"NFT #{offer['id']}"
        description = (
            f"Сделка #{offer['id']}. {offer['nft_title'][:80]}. "
            f"{offer['amount']} Stars. Средства удерживаются ботом до подтверждения "
            "получения NFT. Выплата продавцу выполняется оператором."
        )[:255]
        try:
            invoice_url = await self.bot.create_invoice_link(
                title=title,
                description=description,
                payload=f"offer:{offer['id']}:{nonce}",
                currency="XTR",
                prices=[
                    LabeledPrice(
                        label=f"NFT: {self._short_title(offer['nft_title'], 24)}",
                        amount=int(offer["amount"]),
                    )
                ],
                provider_token="",
            )
        except TelegramAPIError as exc:
            logger.warning("Не удалось создать счёт для #%s: %s", offer["id"], exc.message)
            await self._user_or_group(
                offer,
                user.id,
                "Не удалось создать счёт Telegram Stars. Попробуйте позже.",
                group_text=f"{self._seller_label(offer)}, не удалось создать счёт.",
            )
            return

        ok = await self.db.set_payment_pending(
            offer["id"], nonce, invoice_url, payment_due_at
        )
        if not ok:
            await self._notify_user(
                user.id,
                "Статус сделки уже изменился. Обновите карточку в группе.",
            )
            return

        await self.db.update_offer(
            offer["id"],
            nft_owned_gift_id=proof.owned_gift_id,
            nft_business_connection_id=proof.business_connection_id,
            nft_transfer_mode=proof.transfer_mode,
            nft_transfer_star_count=proof.transfer_star_count,
        )
        await self.db.add_event(offer["id"], user.id, "invoice_created", {"amount": offer["amount"]})
        await self._refresh_card(offer["id"])

        fresh = await self.db.get_offer(offer["id"])
        assert fresh is not None
        pay_text = (
            f"<b>Счёт по сделке №{offer['id']}</b>\n"
            f"NFT: {_esc(offer['nft_title'])}\n"
            f"Сумма: <b>{offer['amount']} Stars</b>\n\n"
            "Оплата проходит через официальный счёт Telegram Stars. "
            "Stars удерживаются ботом до подтверждения получения NFT. "
            "Выплата продавцу выполняется оператором вручную.\n\n"
            f"Счёт действует до {self._fmt_dt(payment_due_at)}."
        )
        sent = await self._notify_user(
            offer["buyer_id"],
            pay_text,
            keyboard=payment_keyboard(invoice_url, int(offer["amount"])),
        )
        await self._notify_user(
            user.id,
            f"Счёт по сделке №{offer['id']} создан. Ожидайте оплату покупателем.",
        )
        if not sent:
            await self._notify_group(
                fresh,
                f"{self._buyer_label(offer)}, счёт по сделке №{offer['id']} "
                f"на <b>{offer['amount']} Stars</b>.\n{pay_text}",
                keyboard=payment_keyboard(invoice_url, int(offer["amount"])),
            )

    async def on_reject(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        user = callback.from_user
        if not self._is_seller(offer, user):
            await self._callback_alert(callback, "Это предложение не для вас.")
            return
        if offer["status"] != OfferStatus.PENDING.value:
            await self._callback_alert(
                callback, f"Статус сделки: {status_label(offer['status'])}."
            )
            return
        if offer["expires_at"] <= _now():
            await self.db.mark_expired(offer["id"])
            await self._refresh_card(offer["id"])
            await self._callback_alert(callback, "Срок действия предложения истёк.")
            return
        ok = await self.db.transition(
            offer["id"],
            {OfferStatus.PENDING.value},
            OfferStatus.REJECTED.value,
            require_unexpired=True,
            closed_at=_now(),
        )
        if not ok:
            if offer["expires_at"] <= _now():
                await self.db.mark_expired(offer["id"])
                await self._refresh_card(offer["id"])
                await self._callback_alert(callback, "Срок действия предложения истёк.")
            else:
                await self._callback_alert(callback, "Предложение уже изменилось.")
            return
        await self.db.add_event(offer["id"], user.id, "rejected")
        await self._refresh_card(offer["id"])
        await self._notify_user(
            offer["buyer_id"],
            f"Продавец отклонил предложение №{offer['id']}.",
        )
        await self._callback_done(callback, "Предложение отклонено")

    async def on_cancel(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        user = callback.from_user
        is_buyer = offer["buyer_id"] == user.id
        is_seller = self._is_seller(offer, user)
        if not (is_buyer or is_seller):
            await self._callback_alert(callback, "У вас нет доступа к этой сделке.")
            return
        allowed = {
            OfferStatus.PENDING.value,
            OfferStatus.ACCEPTED.value,
            OfferStatus.AWAITING_PAYMENT.value,
        }
        if offer["status"] not in allowed:
            await self._callback_alert(
                callback,
                f"Нельзя отменить из статуса «{status_label(offer['status'])}».",
            )
            return
        if offer.get("paid_at"):
            await self._callback_alert(
                callback,
                "Покупатель уже оплатил. Для возврата нужен оператор: /refund "
                + str(offer["id"]),
            )
            return
        if offer["status"] == OfferStatus.PENDING.value and offer["expires_at"] <= _now():
            await self.db.mark_expired(offer["id"])
            await self._refresh_card(offer["id"])
            await self._callback_alert(callback, "Срок действия предложения истёк.")
            return
        ok = await self.db.mark_cancelled(
            offer["id"],
            allowed,
            "Отменена в карточке",
        )
        if not ok:
            await self._callback_alert(callback, "Статус уже изменился.")
            return
        await self.db.add_event(offer["id"], user.id, "cancelled", {"by": user.id})
        await self._refresh_card(offer["id"])
        other = offer["seller_id"] if is_buyer else offer["buyer_id"]
        if other:
            await self._notify_user(
                other,
                f"Сделка №{offer['id']} отменена.",
            )
        await self._callback_done(callback, "Сделка отменена")

    async def on_seller_sent(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        user = callback.from_user
        if not self._is_seller(offer, user):
            await self._callback_alert(callback, "Это не ваша сделка.")
            return
        if offer["status"] != OfferStatus.PAID.value:
            await self._callback_alert(
                callback, f"Статус сделки: {status_label(offer['status'])}."
            )
            return

        await self._callback_done(callback, "Проверяю NFT у покупателя…")
        verified = await self.gifts.buyer_owns_gift(offer["buyer_id"], offer["nft_slug"])
        ok = await self.db.mark_nft_transferred(
            offer["id"],
            method="manual",
            verified=verified,
            verification_method="getUserGifts" if verified else None,
        )
        if not ok:
            await self._notify_user(
                user.id,
                "Статус сделки уже изменился. Обновите карточку в группе.",
            )
            return
        await self.db.add_event(
            offer["id"],
            user.id,
            "nft_marked_sent",
            {"verified": verified},
        )
        await self._refresh_card(offer["id"])
        fresh = await self.db.get_offer(offer["id"])
        assert fresh is not None
        verify_text = (
            " NFT найден в профиле покупателя."
            if verified
            else " Автоматическая проверка профиля покупателя недоступна — нужно подтверждение."
        )
        confirm_text = (
            f"<b>NFT по сделке №{offer['id']} передан</b>\n"
            f"Проверьте NFT и подтвердите получение.\n{verify_text}"
        )
        sent = await self._notify_user(
            offer["buyer_id"],
            confirm_text,
            keyboard=buyer_confirm_keyboard(offer["id"]),
        )
        if not sent:
            await self._notify_group(
                fresh,
                f"{self._buyer_label(offer)}, продавец отметил передачу NFT. "
                f"Подтвердите получение.\n{verify_text}",
                keyboard=buyer_confirm_keyboard(offer["id"]),
            )

    async def on_buyer_confirm(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        user = callback.from_user
        if user.id != offer["buyer_id"]:
            await self._callback_alert(callback, "Подтвердить получение может только покупатель.")
            return
        if offer["status"] != OfferStatus.NFT_TRANSFERRED.value:
            await self._callback_alert(
                callback, f"Статус сделки: {status_label(offer['status'])}."
            )
            return
        ok = await self.db.mark_payout_pending(offer["id"])
        if not ok:
            await self._callback_alert(callback, "Статус уже изменился.")
            return
        await self.db.add_event(offer["id"], user.id, "buyer_confirmed")
        await self._refresh_card(offer["id"])
        fresh = await self.db.get_offer(offer["id"])
        assert fresh is not None
        await self._notify_user(
            user.id,
            f"Получение NFT по сделке №{offer['id']} подтверждено. "
            "Выплата продавцу будет отмечена оператором.",
        )
        if offer.get("seller_id"):
            await self._notify_user(
                offer["seller_id"],
                f"Покупатель подтвердил получение NFT по сделке №{offer['id']}. "
                f"К выплате: {offer['amount']} Stars. Выплата выполняется оператором.",
            )
        await self._notify_group(
            fresh,
            f"Покупатель подтвердил получение NFT по сделке №{offer['id']}. "
            "Ожидается выплата продавцу оператором.",
        )
        await self._alert_admins(
            f"<b>Сделка №{offer['id']} готова к выплате</b>\n"
            f"Продавец: {self._seller_label(offer)}\n"
            f"Сумма: <b>{offer['amount']} Stars</b>\n"
            f"NFT: {self._nft_link(offer)}\n\n"
            f"Выполните внешнюю выплату и отметьте её:\n"
            f"<code>/payout {offer['id']} ССЫЛКА_ИЛИ_НОМЕР</code>"
        )
        await self._callback_done(callback, "Получение подтверждено")

    async def on_dispute(self, callback: CallbackQuery) -> None:
        if not await self._guard_callback(callback):
            return
        offer = await self.db.get_offer(int(callback.data.split(":")[1]))
        if offer is None:
            await self._callback_alert(callback, "Сделка не найдена.")
            return
        user = callback.from_user
        is_admin = await self.is_payment_admin(user.id)
        participant = (
            user.id == offer["buyer_id"]
            or user.id == offer.get("seller_id")
            or is_admin
        )
        if not participant:
            await self._callback_alert(callback, "У вас нет доступа к этой сделке.")
            return
        if offer["status"] not in {
            OfferStatus.PAID.value,
            OfferStatus.TRANSFERRING.value,
            OfferStatus.NFT_TRANSFERRED.value,
            OfferStatus.PAYOUT_PENDING.value,
            OfferStatus.DISPUTED.value,
        }:
            await self._callback_alert(
                callback, f"Нельзя открыть спор из статуса «{status_label(offer['status'])}»."
            )
            return
        if offer["status"] == OfferStatus.DISPUTED.value:
            await self._callback_done(callback, "Спор уже открыт")
            return
        ok = await self.db.mark_disputed(offer["id"])
        if not ok:
            await self._callback_alert(callback, "Статус уже изменился.")
            return
        await self.db.add_event(offer["id"], user.id, "dispute_opened")
        await self._refresh_card(offer["id"])
        fresh = await self.db.get_offer(offer["id"])
        assert fresh is not None
        await self._notify_group(
            fresh,
            f"По сделке №{offer['id']} открыт спор. Оператор уведомлён.",
        )
        await self._alert_admins(
            f"<b>Спор по сделке №{offer['id']}</b>\n"
            f"Покупатель: {self._buyer_label(offer)}\n"
            f"Продавец: {self._seller_label(offer)}\n"
            f"Сумма: {offer['amount']} Stars\n"
            f"Статус: {status_label(fresh['status'])}\n"
            f"NFT: {self._nft_link(offer)}"
        )
        await self._callback_done(callback, "Оператор уведомлён")

    # -------------------------------------------------------------- payments

    async def handle_pre_checkout(self, query: PreCheckoutQuery) -> tuple[bool, str | None]:
        payload = query.invoice_payload or ""
        parts = payload.split(":")
        if len(parts) != 3 or parts[0] != "offer":
            return False, "Некорректный счёт."
        try:
            offer_id = int(parts[1])
        except ValueError:
            return False, "Некорректный счёт."
        nonce = parts[2]
        offer = await self.db.get_offer(offer_id)
        if offer is None:
            return False, "Сделка не найдена."
        if offer["buyer_id"] != query.from_user.id:
            return False, "Этот счёт предназначен другому покупателю."
        if offer["status"] != OfferStatus.AWAITING_PAYMENT.value:
            return False, "Счёт больше не активен."
        if offer.get("payment_nonce") != nonce:
            return False, "Счёт устарел."
        if offer.get("payment_due_at") and offer["payment_due_at"] <= _now():
            return False, "Срок действия счёта истёк."
        if query.currency != "XTR":
            return False, "Ожидается оплата в Telegram Stars."
        if query.total_amount != int(offer["amount"]):
            return False, "Сумма счёта не совпадает."
        return True, None

    async def _alert_admins(self, text: str) -> None:
        admin_ids: set[int] = set(self.settings.admin_ids)
        try:
            admin_ids.update(await self.db.list_staff_ids())
        except Exception:
            pass
        for admin_id in admin_ids:
            await self._notify_user(admin_id, text)

    async def _refund_charge(
        self,
        *,
        user_id: int,
        charge_id: str,
        amount: int | None,
        offer_id: int | None,
        reason: str,
    ) -> bool:
        claimed = await self.db.claim_refund(
            charge_id=charge_id,
            offer_id=offer_id,
            user_id=user_id,
            amount=amount,
            reason=reason,
        )
        if not claimed:
            logger.info("Возврат по charge %s уже выполнялся", charge_id)
            return True

        try:
            await self.bot.refund_star_payment(
                user_id=user_id,
                telegram_payment_charge_id=charge_id,
            )
        except TelegramAPIError as exc:
            await self.db.release_refund(charge_id)
            logger.error("Не удалось вернуть оплату %s: %s", charge_id, exc.message)
            await self._alert_admins(
                "<b>Критично:</b> не удалось вернуть Stars.\n"
                f"Пользователь: <code>{user_id}</code>\n"
                f"Charge: <code>{_esc(charge_id)}</code>\n"
                f"Причина: {_esc(reason)}\n"
                f"Ошибка: {_esc(exc.message)}"
            )
            return False

        if offer_id is not None:
            await self.db.add_event(
                offer_id,
                self.bot.id,
                "payment_refunded",
                {"charge_id": charge_id, "reason": reason},
            )
        suffix = f" по сделке №{offer_id}" if offer_id is not None else ""
        await self._notify_user(
            user_id,
            f"<b>Оплата{suffix} возвращена</b>\n"
            f"Сумма: {amount if amount is not None else '—'} Stars\n"
            f"{_esc(reason)}",
        )
        return True

    async def handle_successful_payment(self, message: Message) -> None:
        payment = message.successful_payment
        if payment is None or message.from_user is None:
            return

        payer_id = message.from_user.id
        charge_id = payment.telegram_payment_charge_id
        paid_amount = int(payment.total_amount)
        parts = (payment.invoice_payload or "").split(":")
        if len(parts) != 3 or parts[0] != "offer":
            logger.warning("Неизвестный payload оплаты")
            await self._refund_charge(
                user_id=payer_id,
                charge_id=charge_id,
                amount=paid_amount,
                offer_id=None,
                reason="Некорректный счёт. Stars возвращены автоматически.",
            )
            return

        try:
            offer_id = int(parts[1])
        except ValueError:
            logger.warning("Некорректный offer_id в payload")
            await self._refund_charge(
                user_id=payer_id,
                charge_id=charge_id,
                amount=paid_amount,
                offer_id=None,
                reason="Некорректный счёт. Stars возвращены автоматически.",
            )
            return

        nonce = parts[2]
        offer = await self.db.get_offer(offer_id)
        if offer is None:
            logger.warning("Оплата по неизвестной сделке #%s", offer_id)
            await self._refund_charge(
                user_id=payer_id,
                charge_id=charge_id,
                amount=paid_amount,
                offer_id=None,
                reason="Сделка не найдена. Stars возвращены автоматически.",
            )
            return

        if payment.currency != "XTR":
            logger.warning("Оплата #%s в валюте %s", offer_id, payment.currency)
            await self._refund_charge(
                user_id=payer_id,
                charge_id=charge_id,
                amount=paid_amount,
                offer_id=offer_id,
                reason="Неверная валюта счёта. Stars возвращены автоматически.",
            )
            return

        if payer_id != offer["buyer_id"]:
            logger.warning("Оплата #%s от неверного пользователя", offer_id)
            await self._refund_charge(
                user_id=payer_id,
                charge_id=charge_id,
                amount=paid_amount,
                offer_id=offer_id,
                reason="Счёт предназначен другому покупателю. Stars возвращены автоматически.",
            )
            return

        if paid_amount != int(offer["amount"]):
            logger.warning(
                "Оплата #%s на сумму %s вместо %s",
                offer_id,
                paid_amount,
                offer["amount"],
            )
            await self._refund_charge(
                user_id=payer_id,
                charge_id=charge_id,
                amount=paid_amount,
                offer_id=offer_id,
                reason="Сумма оплаты не совпала со счётом. Stars возвращены автоматически.",
            )
            return

        try:
            ok = await self.db.mark_paid(
                offer_id=offer_id,
                buyer_id=payer_id,
                amount=int(offer["amount"]),
                nonce=nonce,
                charge_id=charge_id,
                provider_charge_id=payment.provider_payment_charge_id,
                paid_amount=paid_amount,
            )
        except IntegrityError:
            logger.error(
                "Конфликт активных сделок при оплате #%s; оплата будет возвращена",
                offer_id,
            )
            ok = False
        if not ok:
            if await self.db.charge_exists(charge_id):
                logger.info("Повторное уведомление об оплате по сделке #%s", offer_id)
                return
            logger.warning("Оплата по сделке #%s не зачтена, возвращаю Stars", offer_id)
            await self._refund_charge(
                user_id=payer_id,
                charge_id=charge_id,
                amount=paid_amount,
                offer_id=offer_id,
                reason=(
                    "Оплата не была зачтена: счёт устарел или сделка уже "
                    "изменилась. Stars возвращены автоматически."
                ),
            )
            return

        await self.db.add_event(
            offer_id,
            message.from_user.id,
            "payment_received",
            {
                "amount": payment.total_amount,
                "charge_id": payment.telegram_payment_charge_id,
            },
        )
        await self._refresh_card(offer_id)
        offer = await self.db.get_offer(offer_id)
        assert offer is not None

        await self._notify_user(
            offer["buyer_id"],
            f"<b>Оплата по сделке №{offer_id} получена</b>\n"
            f"{offer['amount']} Stars удерживаются ботом до подтверждения получения NFT.",
        )
        await self._alert_admins(
            f"<b>Оплата по сделке №{offer_id}</b>\n"
            f"Сумма: {offer['amount']} Stars\n"
            f"Покупатель: {self._buyer_label(offer)}\n"
            f"Продавец: {self._seller_label(offer)}\n"
            f"Статус: {status_label(offer['status'])}"
        )

        auto_transfer = bool(
            self.settings.business_auto_transfer
            and offer.get("nft_transfer_mode") == "business"
            and offer.get("nft_business_connection_id")
            and offer.get("nft_owned_gift_id")
        )
        if auto_transfer:
            await self._try_auto_transfer(offer)
        else:
            seller_notice = (
                f"<b>Покупатель оплатил сделку №{offer_id}</b>\n"
                f"Получено: {offer['amount']} Stars.\n"
                "Передайте NFT покупателю. Если передали — нажмите кнопку."
            )
            seller_id = offer.get("seller_id")
            sent = await self._notify_user(
                seller_id,
                seller_notice,
                keyboard=seller_paid_keyboard(offer_id),
            ) if seller_id else False
            if not sent:
                await self._notify_group(
                    offer,
                    f"{self._seller_label(offer)}, покупатель оплатил сделку №{offer_id}. "
                    "Передайте NFT покупателю.",
                    keyboard=seller_paid_keyboard(offer_id),
                )
            await self._notify_user(
                offer["buyer_id"],
                "Ожидайте передачу NFT продавцом. После передачи подтвердите получение.",
            )

    async def _try_auto_transfer(self, offer: dict[str, Any]) -> None:
        seller_id = offer.get("seller_id")
        if not seller_id:
            return
        started = await self.db.transition(
            offer["id"],
            {OfferStatus.PAID.value},
            OfferStatus.TRANSFERRING.value,
        )
        if not started:
            return
        await self.db.add_event(offer["id"], self.bot.id, "auto_transfer_started")
        await self._refresh_card(offer["id"])

        try:
            proof = await self.gifts.verify_owner(seller_id, offer["nft_slug"])
            if not proof.can_auto_transfer:
                raise GiftError("автопередача недоступна")
            transfer_id = await self.gifts.transfer_to_buyer(
                seller_id=seller_id,
                buyer_id=offer["buyer_id"],
                proof=proof,
            )
            verified = await self.gifts.buyer_owns_gift(offer["buyer_id"], offer["nft_slug"])
            ok = await self.db.mark_nft_transferred(
                offer["id"],
                method="business",
                transfer_id=transfer_id,
                verified=verified,
                verification_method="getUserGifts" if verified else None,
            )
            if not ok:
                logger.error("NFT передан, но статус #%s не обновился", offer["id"])
                return
            await self.db.add_event(
                offer["id"],
                self.bot.id,
                "auto_transfer_completed",
                {"transfer_id": transfer_id, "verified": verified},
            )
            await self._refresh_card(offer["id"])
            fresh = await self.db.get_offer(offer["id"])
            assert fresh is not None
            text = (
                f"<b>NFT по сделке №{offer['id']} передан автоматически</b>\n"
                + (
                    "NFT найден в профиле покупателя. Подтвердите получение."
                    if verified
                    else "Проверьте NFT и подтвердите получение."
                )
            )
            sent = await self._notify_user(
                offer["buyer_id"],
                text,
                keyboard=buyer_confirm_keyboard(offer["id"]),
            )
            if not sent:
                await self._notify_group(
                    fresh,
                    f"{self._buyer_label(offer)}, NFT передан автоматически. "
                    "Подтвердите получение.",
                    keyboard=buyer_confirm_keyboard(offer["id"]),
                )
            await self._notify_user(
                seller_id,
                f"NFT по сделке №{offer['id']} передан покупателю автоматически. "
                "Ожидается подтверждение получения.",
            )
        except (GiftError, TelegramAPIError) as exc:
            message = str(exc) or "передача не выполнена"
            logger.warning("Автопередача #%s не удалась: %s", offer["id"], message)
            await self.db.transition(
                offer["id"],
                {OfferStatus.TRANSFERRING.value},
                OfferStatus.PAID.value,
                nft_transfer_error=message[:500],
            )
            await self._refresh_card(offer["id"])
            fresh = await self.db.get_offer(offer["id"])
            assert fresh is not None
            await self._notify_user(
                seller_id,
                f"Автоматическая передача NFT по сделке №{offer['id']} не удалась: "
                f"{_esc(message)}. Передайте NFT вручную и нажмите «Я передал NFT».",
                keyboard=seller_paid_keyboard(offer["id"]),
            )
            await self._notify_group(
                fresh,
                f"{self._seller_label(offer)}, автопередача не удалась. "
                "Передайте NFT вручную.",
                keyboard=seller_paid_keyboard(offer["id"]),
            )
            for admin_id in self.settings.admin_ids:
                await self._notify_user(
                    admin_id,
                    f"Автопередача по сделке #{offer['id']} не удалась: {_esc(message)}",
                )

    # --------------------------------------------------------------- admin

    async def refund(self, offer_id: int, admin_id: int) -> str:
        offer = await self.db.get_offer(offer_id)
        if offer is None:
            return "Сделка не найдена."
        if not offer.get("payment_charge_id"):
            return "По сделке нет подтверждённой оплаты."
        if offer["status"] in {
            OfferStatus.COMPLETED.value,
            OfferStatus.REFUNDED.value,
            OfferStatus.CANCELLED.value,
            OfferStatus.REJECTED.value,
            OfferStatus.EXPIRED.value,
        }:
            return f"Возврат невозможен из статуса «{status_label(offer['status'])}»."

        charge_id = offer["payment_charge_id"]
        claimed = await self.db.claim_refund(
            charge_id=charge_id,
            offer_id=offer_id,
            user_id=offer["buyer_id"],
            amount=int(offer.get("paid_amount") or offer["amount"]),
            reason="Возврат администратором",
        )
        if not claimed:
            return "Возврат по этой оплате уже выполнялся."

        try:
            await self.bot.refund_star_payment(
                user_id=offer["buyer_id"],
                telegram_payment_charge_id=charge_id,
            )
        except TelegramAPIError as exc:
            await self.db.release_refund(charge_id)
            logger.warning("Возврат по #%s не удался: %s", offer_id, exc.message)
            return f"Telegram не выполнил возврат: {exc.message}"

        ok = await self.db.mark_refunded(offer_id)
        if not ok:
            logger.error(
                "Возврат по #%s выполнен, но статус не обновился", offer_id
            )
            await self._alert_admins(
                f"<b>Возврат по сделке #{offer_id} выполнен, "
                "но статус не обновился.</b>\n"
                f"Charge: <code>{_esc(charge_id)}</code>\n"
                "Проверьте сделку вручную."
            )
            return "Возврат выполнен, но статус не обновился. Проверьте вручную."
        await self.db.add_event(offer_id, admin_id, "refunded", {"by": admin_id})
        await self._refresh_card(offer_id)
        await self._notify_user(
            offer["buyer_id"],
            f"Возврат {offer['amount']} Stars по сделке №{offer_id} выполнен Telegram.",
        )
        if offer.get("seller_id"):
            await self._notify_user(
                offer["seller_id"],
                f"По сделке №{offer_id} выполнен возврат покупателю.",
            )
        return f"Возврат по сделке №{offer_id} выполнен."

    async def payout(self, offer_id: int, reference: str, admin_id: int) -> str:
        offer = await self.db.get_offer(offer_id)
        if offer is None:
            return "Сделка не найдена."
        if offer["status"] not in {
            OfferStatus.PAYOUT_PENDING.value,
            OfferStatus.DISPUTED.value,
        }:
            return (
                f"Выплата возможна только после подтверждения получения "
                f"(текущий статус: {status_label(offer['status'])})."
            )
        if not reference.strip():
            return "Укажите ссылку/номер внешней выплаты."
        ok = await self.db.mark_completed(offer_id, reference.strip(), admin_id)
        if not ok:
            return "Статус сделки уже изменился."
        await self.db.add_event(
            offer_id,
            admin_id,
            "payout_recorded",
            {"reference": reference.strip(), "amount": offer["amount"]},
        )
        await self._refresh_card(offer_id)
        if offer.get("seller_id"):
            await self._notify_user(
                offer["seller_id"],
                f"<b>Выплата по сделке №{offer_id} отмечена оператором</b>\n"
                f"Сумма: {offer['amount']} Stars\n"
                f"Подтверждение: <code>{_esc(reference)}</code>\n"
                "Выплата выполнена вне Bot API (вручную оператором).",
            )
        await self._notify_user(
            offer["buyer_id"],
            f"Сделка №{offer_id} завершена. Спасибо.",
        )
        return f"Выплата по сделке №{offer_id} отмечена."

    async def reconcile(self, offer_id: int, admin_id: int) -> str:
        offer = await self.db.get_offer(offer_id)
        if offer is None:
            return "Сделка не найдена."
        if offer["status"] not in {
            OfferStatus.PAID.value,
            OfferStatus.TRANSFERRING.value,
            OfferStatus.NFT_TRANSFERRED.value,
            OfferStatus.DISPUTED.value,
        }:
            return f"Сверка не нужна для статуса «{status_label(offer['status'])}»."
        owns = await self.gifts.buyer_owns_gift(offer["buyer_id"], offer["nft_slug"])
        if not owns:
            return "NFT не найден в профиле покупателя. Передайте его вручную."
        if offer["status"] == OfferStatus.NFT_TRANSFERRED.value:
            await self.db.mark_nft_verified(offer_id, "admin_reconcile")
        else:
            ok = await self.db.mark_nft_transferred(
                offer_id,
                method="admin_reconcile",
                verified=True,
                verification_method="admin_reconcile",
            )
            if not ok:
                return "Статус уже изменился."
        await self.db.add_event(offer_id, admin_id, "admin_reconciled")
        await self._refresh_card(offer_id)
        await self._notify_user(
            offer["buyer_id"],
            f"NFT по сделке №{offer_id} найден в вашем профиле. Подтвердите получение.",
            keyboard=buyer_confirm_keyboard(offer_id),
        )
        return f"NFT по сделке №{offer_id} подтверждён в профиле покупателя."

    async def admin_pending_text(self) -> str:
        offers = await self.db.list_by_statuses(
            {
                OfferStatus.PAID.value,
                OfferStatus.TRANSFERRING.value,
                OfferStatus.NFT_TRANSFERRED.value,
                OfferStatus.PAYOUT_PENDING.value,
                OfferStatus.DISPUTED.value,
            },
            limit=20,
        )
        if not offers:
            return "Нет сделок, требующих внимания."
        lines = ["<b>Сделки, требующие внимания</b>"]
        for offer in offers:
            lines.append(
                f"#{offer['id']} · {_esc(self._short_title(offer['nft_title'], 35))} · "
                f"{offer['amount']} Stars · {status_label(offer['status'])}"
            )
        return "\n".join(lines)

    async def admin_stats_text(self) -> str:
        stats = await self.db.stats()
        if not stats:
            return "Статистика пуста."
        lines = ["<b>Статистика сделок</b>"]
        for status, count in sorted(stats.items(), key=lambda item: item[0]):
            lines.append(f"{status_label(status)}: <b>{count}</b>")

        try:
            balance = await self.bot.get_my_star_balance()
            lines.append(f"\nБаланс бота: <b>{balance.amount} Stars</b>")
        except TelegramAPIError:
            lines.append("\nБаланс бота: недоступен")
        return "\n".join(lines)

    async def deal_details_text(self, offer_id: int) -> str:
        offer = await self.db.get_offer(offer_id)
        if offer is None:
            return "Сделка не найдена."
        events = await self.db.get_events(offer_id, limit=8)
        lines = [
            f"<b>Сделка №{offer['id']}</b>",
            f"Статус: <b>{status_label(offer['status'])}</b>",
            f"NFT: {self._nft_link(offer)}",
            f"Покупатель: {self._buyer_label(offer)}",
            f"Продавец: {self._seller_label(offer)}",
            f"Сумма: <b>{offer['amount']} Stars</b>",
            f"Создана: {self._fmt_dt(offer['created_at'])}",
        ]
        if offer.get("paid_at"):
            lines.append(f"Оплачена: {self._fmt_dt(offer['paid_at'])}")
        if offer.get("payment_charge_id"):
            lines.append(f"Charge ID: <code>{_esc(offer['payment_charge_id'])}</code>")
        if offer.get("payout_reference"):
            lines.append(f"Выплата: <code>{_esc(offer['payout_reference'])}</code>")
        if events:
            lines.append("\n<b>История</b>")
            for event in events:
                lines.append(
                    f"{self._fmt_dt(event['created_at'])} · {_esc(event['action'])}"
                )
        return "\n".join(lines)

    async def user_offers_text(self, user_id: int) -> str:
        offers = await self.db.list_user_offers(user_id, limit=10)
        if not offers:
            return "У вас пока нет сделок."
        lines = ["<b>Ваши последние сделки</b>"]
        for offer in offers:
            lines.append(
                f"#{offer['id']} · {_esc(self._short_title(offer['nft_title'], 35))} · "
                f"{offer['amount']} Stars · {status_label(offer['status'])}"
            )
        return "\n".join(lines)

    async def business_status_text(self, user_id: int) -> str:
        conn = await self.db.get_business_connection(user_id)
        if not conn or not conn.get("is_enabled"):
            return (
                "Telegram Business не подключён.\n\n"
                "Чтобы включить автопередачу NFT, подключите бота в "
                "Настройки → Telegram Business → Чат-боты и выдайте права "
                "на просмотр и передачу подарков."
            )
        rights = conn.get("rights") or {}
        lines = ["<b>Telegram Business подключён</b>"]
        lines.append(
            "Просмотр подарков: "
            + ("да" if rights.get("can_view_gifts_and_stars") else "нет")
        )
        lines.append(
            "Передача подарков: "
            + ("да" if rights.get("can_transfer_and_upgrade_gifts") else "нет")
        )
        lines.append(
            "Передача Stars: "
            + ("да" if rights.get("can_transfer_stars") else "нет")
        )
        if not (
            rights.get("can_view_gifts_and_stars")
            and rights.get("can_transfer_and_upgrade_gifts")
        ):
            lines.append(
                "\nДля автопередачи нужны права на просмотр и передачу подарков."
            )
        return "\n".join(lines)

    # --------------------------------------------------------- business update

    async def on_business_connection(self, connection) -> None:
        rights = {}
        if connection.rights is not None:
            rights = connection.rights.model_dump(exclude_none=True)
        await self.db.save_business_connection(
            user_id=connection.user.id,
            connection_id=connection.id,
            user_chat_id=connection.user_chat_id,
            is_enabled=connection.is_enabled,
            rights=rights,
        )
        logger.info(
            "Telegram Business connection user=%s enabled=%s rights=%s",
            connection.user.id,
            connection.is_enabled,
            sorted(key for key, value in rights.items() if value),
        )
        if connection.is_enabled:
            target = connection.user_chat_id or connection.user.id
            await self._notify_user(
                target,
                "<b>Telegram Business подключён</b>\n"
                "Бот будет проверять владение NFT и сможет передать его "
                "покупателю, если выданы права на просмотр и передачу подарков.",
            )
        else:
            await self.db.disable_business_connection(connection.id)

    # -------------------------------------------------------------- maintenance

    async def refresh_pending_cards(self) -> None:
        """Обновляет «действует ещё …» на активных карточках не чаще раза в минуту."""
        for offer in await self.db.pending_offers():
            caption = self._caption(offer)
            if self._last_card_caption.get(offer["id"]) == caption:
                continue
            await self._refresh_card(offer["id"])

    async def expire_offers(self) -> None:
        due = await self.db.due_expirations()
        for offer in due:
            if await self.db.mark_expired(offer["id"]):
                await self.db.add_event(offer["id"], None, "expired")
                await self._refresh_card(offer["id"])
                logger.info("Предложение #%s истекло", offer["id"])

    async def expire_payments(self) -> None:
        due = await self.db.due_payment_timeouts()
        for offer in due:
            if await self.db.mark_cancelled(
                offer["id"],
                {OfferStatus.AWAITING_PAYMENT.value},
                "Истёк срок оплаты",
            ):
                await self.db.add_event(offer["id"], None, "payment_timeout")
                await self._refresh_card(offer["id"])
                await self._notify_user(
                    offer["buyer_id"],
                    f"Срок оплаты по сделке №{offer['id']} истёк. Сделка отменена.",
                )
                if offer.get("seller_id"):
                    await self._notify_user(
                        offer["seller_id"],
                        f"Срок оплаты по сделке №{offer['id']} истёк. Сделка отменена.",
                    )

    # ----------------------------------------------------------------- helpers

    def _is_seller(self, offer: dict[str, Any], user: User) -> bool:
        if offer.get("seller_id") is not None:
            return offer["seller_id"] == user.id
        if offer.get("seller_username") and user.username:
            return offer["seller_username"].lower() == user.username.lower()
        return False

    async def _bind_seller_if_needed(self, offer: dict[str, Any], user: User) -> None:
        if offer.get("seller_id") is None:
            await self.db.bind_seller(
                offer["id"],
                user.id,
                user.username,
                " ".join(p for p in (user.first_name, user.last_name) if p),
            )
