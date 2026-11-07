from __future__ import annotations

import re
from dataclasses import dataclass

from aiogram.types import Message, User

from nft import NFT_URL_RE, parse_nft_link


class OfferParseError(ValueError):
    """Команда похожа на предложение, но заполнена неверно."""


@dataclass(frozen=True, slots=True)
class SellerHint:
    user_id: int | None
    username: str | None
    display_name: str | None


@dataclass(frozen=True, slots=True)
class OfferRequest:
    nft_url: str
    nft_slug: str
    amount: int
    seller: SellerHint


def _clean_username(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lstrip("@").lower() or None


def _display_name(user: User) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part).strip()


def _hint_from_user(user: User) -> SellerHint:
    return SellerHint(
        user_id=user.id,
        username=_clean_username(user.username),
        display_name=_display_name(user) or None,
    )


def _same_seller(first: SellerHint, second: SellerHint) -> bool:
    if first.user_id is not None and second.user_id is not None:
        return first.user_id == second.user_id
    if first.username and second.username:
        return first.username == second.username
    return False


def _is_bot_command_for_us(text: str, bot_username: str) -> tuple[bool, str]:
    match = re.match(r"^/offer(?:@([A-Za-z0-9_]+))?(?=\s|$)", text, re.IGNORECASE)
    if match:
        mentioned = _clean_username(match.group(1))
        if mentioned and mentioned != bot_username.lower():
            return False, text
        return True, text[match.end() :].lstrip()
    return False, text


def _has_bot_mention(text: str, bot_username: str) -> bool:
    return bool(
        re.search(
            rf"(?<![\w@])@{re.escape(bot_username)}(?![\w])",
            text,
            re.IGNORECASE,
        )
    )


def _remove_bot_mention(text: str, bot_username: str) -> str:
    return re.sub(
        rf"(?<![\w@])@{re.escape(bot_username)}(?![\w])",
        " ",
        text,
        count=1,
        flags=re.IGNORECASE,
    )


def _text_mention_users(message: Message, buyer_id: int, bot_username: str) -> list[SellerHint]:
    result: list[SellerHint] = []
    for entity in message.entities or []:
        if entity.type != "text_mention" or entity.user is None:
            continue
        user = entity.user
        if user.id == buyer_id or user.is_bot:
            continue
        result.append(_hint_from_user(user))
    return result


def _username_mentions(text: str, buyer_username: str | None, bot_username: str) -> list[SellerHint]:
    result: list[SellerHint] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{4,31})(?![\w])", text):
        username = _clean_username(match.group(1))
        if not username or username == bot_username.lower():
            continue
        if buyer_username and username == buyer_username:
            continue
        if username in seen:
            continue
        seen.add(username)
        result.append(SellerHint(user_id=None, username=username, display_name=None))
    return result


def parse_offer_message(
    message: Message,
    bot_username: str,
    min_amount: int,
    max_amount: int,
) -> OfferRequest | None:
    """
    Возвращает None, если сообщение не адресовано боту.
    Бросает OfferParseError, если бот упомянут, но команда заполнена неверно.
    """
    if not message.text or not message.from_user or message.from_user.is_bot:
        return None

    text = message.text.strip()
    buyer = message.from_user
    buyer_username = _clean_username(buyer.username)

    is_command, remainder = _is_bot_command_for_us(text, bot_username)
    if not is_command and not _has_bot_mention(text, bot_username):
        return None

    if is_command:
        working = remainder
    else:
        working = _remove_bot_mention(text, bot_username)

    # Ссылка на NFT.
    match = NFT_URL_RE.search(working)
    if not match:
        raise OfferParseError(
            "Не вижу ссылку на NFT. Формат: @бот https://t.me/nft/Name-123 100\n"
            "Команду нужно отправить ответом на сообщение продавца "
            "или добавить @username продавца."
        )
    nft_url = match.group(0).rstrip(".,);]")
    slug = parse_nft_link(nft_url)
    if not slug:
        raise OfferParseError("Некорректная ссылка на NFT.")

    # Продавец: сначала reply, затем text_mention, затем @username.
    reply_seller: SellerHint | None = None
    if message.reply_to_message and message.reply_to_message.from_user:
        replied = message.reply_to_message.from_user
        if replied.is_bot:
            if replied.username and replied.username.lower() == bot_username.lower():
                raise OfferParseError(
                    "Команда отправлена ответом на сообщение бота. "
                    "Ответьте на сообщение продавца."
                )
            raise OfferParseError("Нельзя сделать предложение боту.")
        reply_seller = _hint_from_user(replied)

    explicit_text_mentions = _text_mention_users(message, buyer.id, bot_username)
    plain_mentions = _username_mentions(working, buyer_username, bot_username)
    explicit_mentions = explicit_text_mentions + plain_mentions

    seller = reply_seller
    if seller and explicit_mentions:
        for hint in explicit_mentions:
            same_id = seller.user_id is not None and hint.user_id == seller.user_id
            same_username = (
                seller.username is not None
                and hint.username is not None
                and seller.username == hint.username
            )
            if not same_id and not same_username:
                raise OfferParseError(
                    "Продавец указан неоднозначно: ответ и @username относятся "
                    "к разным пользователям."
                )
    elif explicit_mentions:
        unique: list[SellerHint] = []
        for hint in explicit_mentions:
            if not any(_same_seller(hint, item) for item in unique):
                unique.append(hint)
        if len(unique) > 1:
            raise OfferParseError(
                "Указано несколько продавцов. Оставьте одного @username "
                "или ответьте на сообщение продавца."
            )
        seller = unique[0]

    if seller is None:
        raise OfferParseError(
            "Не удалось определить продавца. Ответьте этой командой на сообщение "
            "продавца или добавьте его @username.\n\n"
            "Пример: @бот @seller https://t.me/nft/Name-123 100"
        )

    if seller.user_id == buyer.id:
        raise OfferParseError("Нельзя сделать предложение самому себе.")
    if seller.username and buyer_username and seller.username == buyer_username:
        raise OfferParseError("Нельзя сделать предложение самому себе.")

    # Сумма: убираем ссылку и упоминания, чтобы не поймать цифры из slug/username.
    amount_text = working.replace(nft_url, " ")
    amount_text = re.sub(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{4,31}(?![\w])", " ", amount_text)
    numbers = re.findall(r"(?<![\d])(\d{1,7})(?![\d])", amount_text)
    if not numbers:
        raise OfferParseError(
            "Не вижу количество Stars. Пример: @бот https://t.me/nft/Name-123 100"
        )
    if len(numbers) > 1:
        raise OfferParseError("В команде должно быть только одно число — количество Stars.")

    amount = int(numbers[0])
    if amount < min_amount:
        raise OfferParseError(f"Минимальная сумма — {min_amount} Stars.")
    if amount > max_amount:
        raise OfferParseError(f"Максимальная сумма — {max_amount} Stars.")

    return OfferRequest(
        nft_url=nft_url,
        nft_slug=slug,
        amount=amount,
        seller=seller,
    )
