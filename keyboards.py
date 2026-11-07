from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать предложение",
                    callback_data="menu:create",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Мои предложения",
                    callback_data="menu:offers",
                ),
                InlineKeyboardButton(
                    text="История сделок",
                    callback_data="menu:history",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Уведомления",
                    callback_data="menu:notifications",
                ),
                InlineKeyboardButton(
                    text="Правила обмена",
                    callback_data="menu:rules",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Поддержка",
                    callback_data="menu:support",
                ),
                InlineKeyboardButton(
                    text="Мой профиль",
                    callback_data="menu:profile",
                ),
            ],
        ]
    )


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:back")]
        ]
    )


def notifications_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    toggle = "Выключить уведомления" if enabled else "Включить уведомления"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle, callback_data="menu:notif_toggle")],
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:back")],
        ]
    )


def offer_list_keyboard(offers: list[int]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"Сделка №{offer_id}",
                callback_data=f"menu:deal:{offer_id}",
            )
        ]
        for offer_id in offers
    ]
    rows.append(
        [InlineKeyboardButton(text="Назад в меню", callback_data="menu:back")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)



def offer_main_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Принять",
                    callback_data=f"offer:{offer_id}:accept",
                ),
                InlineKeyboardButton(
                    text="Отклонить",
                    callback_data=f"offer:{offer_id}:reject",
                ),
            ]
        ]
    )


def offer_details_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить сделку",
                    callback_data=f"offer:{offer_id}:confirm",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"offer:{offer_id}:cancel",
                ),
            ]
        ]
    )


def seller_paid_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Я передал NFT",
                    callback_data=f"offer:{offer_id}:seller_sent",
                ),
                InlineKeyboardButton(
                    text="Проблема",
                    callback_data=f"offer:{offer_id}:dispute",
                ),
            ]
        ]
    )


def buyer_confirm_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить получение",
                    callback_data=f"offer:{offer_id}:buyer_confirm",
                ),
                InlineKeyboardButton(
                    text="Проблема",
                    callback_data=f"offer:{offer_id}:dispute",
                ),
            ]
        ]
    )


def dispute_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сообщить о проблеме",
                    callback_data=f"offer:{offer_id}:dispute",
                )
            ]
        ]
    )


def payment_keyboard(url: str, amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Оплатить {amount} Stars",
                    url=url,
                )
            ]
        ]
    )


def admin_refund_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Вернуть Stars покупателю",
                    callback_data=f"offer:{offer_id}:admin_refund",
                )
            ]
        ]
    )
