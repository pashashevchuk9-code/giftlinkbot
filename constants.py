from __future__ import annotations

from enum import Enum

# Срок жизни предложения зафиксирован требованием: ровно 48 часов.
OFFER_TTL_HOURS = 48
OFFER_TTL_SECONDS = OFFER_TTL_HOURS * 3600


class OfferStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    TRANSFERRING = "transferring"
    NFT_TRANSFERRED = "nft_transferred"
    PAYOUT_PENDING = "payout_pending"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"
    REFUNDED = "refunded"
    FAILED = "failed"


STATUS_LABELS: dict[str, str] = {
    OfferStatus.PENDING.value: "Ожидает решения",
    OfferStatus.ACCEPTED.value: "Принято, ожидает подтверждения",
    OfferStatus.AWAITING_PAYMENT.value: "Ожидает оплаты",
    OfferStatus.PAID.value: "Оплачено, ожидает передачи NFT",
    OfferStatus.TRANSFERRING.value: "Передача NFT",
    OfferStatus.NFT_TRANSFERRED.value: "NFT передан, ожидает подтверждения",
    OfferStatus.PAYOUT_PENDING.value: "Получение подтверждено, ожидает выплаты",
    OfferStatus.COMPLETED.value: "Завершена",
    OfferStatus.REJECTED.value: "Отклонена",
    OfferStatus.EXPIRED.value: "Истекло",
    OfferStatus.CANCELLED.value: "Отменена",
    OfferStatus.DISPUTED.value: "Спор, ожидает оператора",
    OfferStatus.REFUNDED.value: "Возврат выполнен",
    OfferStatus.FAILED.value: "Ошибка",
}

ACTIVE_PENDING = {OfferStatus.PENDING.value}
PAYMENT_ALLOWED = {OfferStatus.AWAITING_PAYMENT.value}
PAID_STATES = {
    OfferStatus.PAID.value,
    OfferStatus.TRANSFERRING.value,
    OfferStatus.NFT_TRANSFERRED.value,
    OfferStatus.PAYOUT_PENDING.value,
    OfferStatus.DISPUTED.value,
}
CLOSED_STATES = {
    OfferStatus.COMPLETED.value,
    OfferStatus.REJECTED.value,
    OfferStatus.EXPIRED.value,
    OfferStatus.CANCELLED.value,
    OfferStatus.REFUNDED.value,
    OfferStatus.FAILED.value,
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
