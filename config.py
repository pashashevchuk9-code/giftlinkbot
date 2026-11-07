from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from constants import OFFER_TTL_SECONDS

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{25,}$")


class ConfigError(RuntimeError):
    """Ошибка конфигурации без вывода секретов."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должен быть целым числом") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} должен быть в диапазоне {minimum}..{maximum}")
    return value


def _parse_id_list(raw: str | None, name: str) -> frozenset[int]:
    if not raw or not raw.strip():
        return frozenset()
    result: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            user_id = int(chunk)
        except ValueError as exc:
            raise ConfigError(
                f"{name} должен содержать числовые Telegram ID через запятую"
            ) from exc
        if user_id <= 0:
            raise ConfigError(f"{name} содержит некорректный ID")
        result.add(user_id)
    return frozenset(result)


def _parse_admin_ids(raw: str | None) -> frozenset[int]:
    return _parse_id_list(raw, "ADMIN_IDS")


def _parse_owner_ids() -> frozenset[int]:
    """OWNER_ID (один) и OWNER_IDS (несколько) — только из конфигурации."""
    parts = [
        os.getenv("OWNER_ID", ""),
        os.getenv("OWNER_IDS", ""),
    ]
    return _parse_id_list(",".join(part for part in parts if part), "OWNER_ID")


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str = field(repr=False)
    database_path: Path
    admin_ids: frozenset[int]
    owner_ids: frozenset[int]
    offer_ttl_seconds: int
    payment_window_seconds: int
    payments_enabled: bool
    operator_payout_ack: bool
    timezone_name: str
    log_level: str
    min_offer_stars: int
    max_offer_stars: int
    support_contact: str | None
    business_auto_transfer: bool

    @classmethod
    def load(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError("BOT_TOKEN не задан. Заполните .env")
        if not _TOKEN_RE.match(token):
            raise ConfigError(
                "BOT_TOKEN имеет неверный формат. Проверьте токен в .env, не выводя его в консоль."
            )

        payment_minutes = _env_int("PAYMENT_WINDOW_MINUTES", 30, 5, 24 * 60)
        min_stars = _env_int("MIN_OFFER_STARS", 1, 1, 1_000_000)
        max_stars = _env_int("MAX_OFFER_STARS", 1_000_000, min_stars, 10_000_000)

        timezone_name = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(f"Неизвестный часовой пояс: {timezone_name}") from exc

        raw_path = os.getenv("DATABASE_PATH", "data/nft_offers.sqlite3").strip()
        db_path = Path(raw_path).expanduser()
        if not db_path.is_absolute():
            db_path = BASE_DIR / db_path

        support = os.getenv("SUPPORT_CONTACT", "").strip() or None

        return cls(
            bot_token=token,
            database_path=db_path,
            admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
            owner_ids=_parse_owner_ids(),
            offer_ttl_seconds=OFFER_TTL_SECONDS,
            payment_window_seconds=payment_minutes * 60,
            payments_enabled=_env_bool("PAYMENTS_ENABLED", False),
            operator_payout_ack=_env_bool("OPERATOR_PAYOUT_ACK", False),
            timezone_name=timezone_name,
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
            min_offer_stars=min_stars,
            max_offer_stars=max_stars,
            support_contact=support,
            business_auto_transfer=_env_bool("BUSINESS_AUTO_TRANSFER", True),
        )

    @property
    def payments_available(self) -> bool:
        """Оплата включается только после явного подтверждения ручных выплат."""
        return (
            self.payments_enabled
            and self.operator_payout_ack
            and bool(self.admin_ids or self.owner_ids)
        )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)
