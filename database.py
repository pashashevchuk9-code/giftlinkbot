from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from constants import OfferStatus
from roles import Role

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    role TEXT NOT NULL DEFAULT 'USER',
    registered_at INTEGER,
    is_banned INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    banned_at INTEGER,
    banned_by INTEGER,
    restriction_until INTEGER,
    restriction_reason TEXT,
    language TEXT NOT NULL DEFAULT 'ru',
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_chat_id INTEGER,
    group_message_id INTEGER,
    inline_message_id TEXT,
    card_kind TEXT NOT NULL DEFAULT 'text',
    buyer_id INTEGER NOT NULL,
    buyer_username TEXT,
    buyer_name TEXT NOT NULL,
    seller_id INTEGER,
    seller_username TEXT,
    seller_name TEXT,
    nft_url TEXT NOT NULL,
    nft_slug TEXT NOT NULL,
    nft_title TEXT NOT NULL,
    nft_image_url TEXT,
    nft_description TEXT,
    nft_owner_label TEXT,
    language TEXT NOT NULL DEFAULT 'ru',
    amount INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    accepted_at INTEGER,
    seller_confirmed_at INTEGER,
    payment_due_at INTEGER,
    paid_amount INTEGER,
    paid_at INTEGER,
    nft_sent_at INTEGER,
    nft_verified_at INTEGER,
    nft_verification_method TEXT,
    completed_at INTEGER,
    closed_at INTEGER,
    payment_charge_id TEXT,
    payment_provider_charge_id TEXT,
    payment_nonce TEXT,
    invoice_url TEXT,
    nft_owned_gift_id TEXT,
    nft_business_connection_id TEXT,
    nft_transfer_mode TEXT,
    nft_transfer_star_count INTEGER,
    nft_transfer_id TEXT,
    nft_transfer_error TEXT,
    payout_reference TEXT,
    payout_at INTEGER,
    payout_by INTEGER,
    cancel_reason TEXT,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_offers_status_expires
    ON offers(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_offers_buyer
    ON offers(buyer_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_offers_seller
    ON offers(seller_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_offers_payment_due
    ON offers(status, payment_due_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_offers_payment_charge
    ON offers(payment_charge_id)
    WHERE payment_charge_id IS NOT NULL;

-- Один продавец не может вести две активные сделки по одному и тому же NFT.
CREATE UNIQUE INDEX IF NOT EXISTS idx_offers_one_active_nft
    ON offers(nft_slug, seller_id)
    WHERE seller_id IS NOT NULL
      AND status IN (
          'accepted', 'awaiting_payment', 'paid', 'transferring',
          'nft_transferred', 'payout_pending', 'disputed'
      );

CREATE TABLE IF NOT EXISTS payment_charges (
    charge_id TEXT PRIMARY KEY,
    offer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    charge_id TEXT PRIMARY KEY,
    offer_id INTEGER,
    user_id INTEGER NOT NULL,
    amount INTEGER,
    reason TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS business_connections (
    user_id INTEGER PRIMARY KEY,
    connection_id TEXT NOT NULL UNIQUE,
    user_chat_id INTEGER,
    is_enabled INTEGER NOT NULL,
    rights_json TEXT,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER NOT NULL,
    actor_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_offer
    ON events(offer_id, id DESC);

-- Роли, доступ, технический режим и журнал административных действий.

CREATE TABLE IF NOT EXISTS admin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_id INTEGER,
    details TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_log_created
    ON admin_log(created_at DESC);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    reason TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_warnings_user
    ON warnings(user_id, id DESC);

CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    traceback TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_error_log_created
    ON error_log(created_at DESC);

CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS service_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_user
    ON notifications(user_id, id DESC);

CREATE TABLE IF NOT EXISTS notification_prefs (
    user_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL
);
"""

_ALLOWED_OFFER_FIELDS = {
    "group_message_id",
    "card_kind",
    "seller_id",
    "seller_username",
    "seller_name",
    "status",
    "expires_at",
    "accepted_at",
    "seller_confirmed_at",
    "payment_due_at",
    "paid_amount",
    "paid_at",
    "nft_sent_at",
    "nft_verified_at",
    "nft_verification_method",
    "completed_at",
    "closed_at",
    "payment_charge_id",
    "payment_provider_charge_id",
    "payment_nonce",
    "invoice_url",
    "nft_owned_gift_id",
    "nft_business_connection_id",
    "nft_transfer_mode",
    "nft_transfer_star_count",
    "nft_transfer_id",
    "nft_transfer_error",
    "payout_reference",
    "payout_at",
    "payout_by",
    "cancel_reason",
    "updated_at",
}


def _now() -> int:
    return int(time.time())


def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не инициализирована")
        return self._conn

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(
            self.path,
            isolation_level=None,
            timeout=10,
        )
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        await self._migrate()

    async def _migrate(self) -> None:
        """Добавляет новые колонки в уже существующую таблицу users."""
        cursor = await self.conn.execute("PRAGMA table_info(users)")
        columns = {row["name"] for row in await cursor.fetchall()}
        additions: dict[str, str] = {
            "role": "TEXT NOT NULL DEFAULT 'USER'",
            "registered_at": "INTEGER",
            "is_banned": "INTEGER NOT NULL DEFAULT 0",
            "ban_reason": "TEXT",
            "banned_at": "INTEGER",
            "banned_by": "INTEGER",
            "restriction_until": "INTEGER",
            "restriction_reason": "TEXT",
            "language": "TEXT NOT NULL DEFAULT 'ru'",
        }
        for name, ddl in additions.items():
            if name not in columns:
                await self.conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

        now = _now()
        await self.conn.execute(
            "UPDATE users SET registered_at=COALESCE(registered_at, updated_at, ?)",
            (now,),
        )
        await self.conn.execute(
            "UPDATE users SET role=? WHERE role IS NULL OR role=''",
            (Role.USER.value,),
        )
        await self.conn.execute(
            "UPDATE users SET is_banned=0 WHERE is_banned IS NULL"
        )
        await self._migrate_offers()

    async def _migrate_offers(self) -> None:
        cursor = await self.conn.execute("PRAGMA table_info(offers)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "inline_message_id" not in columns:
            await self.conn.execute(
                "ALTER TABLE offers ADD COLUMN inline_message_id TEXT"
            )
        if "language" not in columns:
            await self.conn.execute(
                "ALTER TABLE offers ADD COLUMN language TEXT NOT NULL DEFAULT 'ru'"
            )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def upsert_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> None:
        now = _now()
        await self.conn.execute(
            """
            INSERT INTO users(
                user_id, username, first_name, last_name, role, registered_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                username,
                first_name,
                last_name,
                Role.USER.value,
                now,
                now,
            ),
        )

    async def ensure_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        *,
        owner_ids: frozenset[int] | set[int] | tuple[int, ...] = (),
    ) -> dict[str, Any]:
        """Регистрирует пользователя и синхронизирует OWNER по конфигурации."""
        await self.upsert_user(user_id, username, first_name, last_name)
        owners = set(owner_ids)
        if user_id in owners:
            await self.conn.execute(
                "UPDATE users SET role=? WHERE user_id=? AND role<>?",
                (Role.OWNER.value, user_id, Role.OWNER.value),
            )
        else:
            # OWNER определяется только ID из конфигурации.
            await self.conn.execute(
                "UPDATE users SET role=? WHERE user_id=? AND role=?",
                (Role.USER.value, user_id, Role.OWNER.value),
            )
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        )
        return _row_to_dict(await cursor.fetchone())

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE lower(username)=lower(?) LIMIT 1",
            (username.lstrip("@"),),
        )
        return _row_to_dict(await cursor.fetchone())

    async def set_user_language(self, user_id: int, language: str) -> bool:
        cursor = await self.conn.execute(
            "UPDATE users SET language=?, updated_at=? WHERE user_id=?",
            (language, _now(), user_id),
        )
        return cursor.rowcount == 1

    async def get_user_language(self, user_id: int) -> str:
        cursor = await self.conn.execute(
            "SELECT language FROM users WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        return row["language"] if row and row["language"] else "ru"

    async def set_user_role(self, user_id: int, role: Role | str) -> bool:
        value = role.value if isinstance(role, Role) else str(role)
        cursor = await self.conn.execute(
            "UPDATE users SET role=?, updated_at=? WHERE user_id=?",
            (value, _now(), user_id),
        )
        return cursor.rowcount == 1

    async def seed_env_roles(
        self,
        *,
        admin_ids: frozenset[int] | set[int] = frozenset(),
        owner_ids: frozenset[int] | set[int] = frozenset(),
    ) -> None:
        """ADMIN_IDS из .env получают ADMIN только если роль ещё USER."""
        for user_id in owner_ids:
            await self.conn.execute(
                "UPDATE users SET role=? WHERE user_id=? AND role<>?",
                (Role.OWNER.value, user_id, Role.OWNER.value),
            )
        for user_id in admin_ids:
            if user_id in owner_ids:
                continue
            await self.conn.execute(
                "UPDATE users SET role=? WHERE user_id=? AND role=?",
                (Role.ADMIN.value, user_id, Role.USER.value),
            )

    async def set_ban(
        self,
        user_id: int,
        *,
        banned: bool,
        admin_id: int,
        reason: str | None = None,
    ) -> bool:
        now = _now()
        cursor = await self.conn.execute(
            """
            UPDATE users
            SET is_banned=?,
                ban_reason=?,
                banned_at=?,
                banned_by=?,
                updated_at=?
            WHERE user_id=?
            """,
            (
                1 if banned else 0,
                reason if banned else None,
                now if banned else None,
                admin_id if banned else None,
                now,
                user_id,
            ),
        )
        return cursor.rowcount == 1

    async def add_warning(
        self,
        user_id: int,
        admin_id: int,
        reason: str | None,
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO warnings(user_id, admin_id, reason, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (user_id, admin_id, reason, _now()),
        )
        return int(cursor.lastrowid)

    async def list_warnings(
        self, user_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM warnings
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def count_warnings(self, user_id: int) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM warnings WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def set_restriction(
        self,
        user_id: int,
        *,
        until: int | None,
        reason: str | None,
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE users
            SET restriction_until=?, restriction_reason=?, updated_at=?
            WHERE user_id=?
            """,
            (until, reason if until else None, _now(), user_id),
        )
        return cursor.rowcount == 1

    async def count_completed_deals(self, user_id: int) -> int:
        cursor = await self.conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM offers
            WHERE status=? AND (buyer_id=? OR seller_id=?)
            """,
            (OfferStatus.COMPLETED.value, user_id, user_id),
        )
        row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def count_users(self) -> int:
        cursor = await self.conn.execute("SELECT COUNT(*) AS cnt FROM users")
        row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def count_users_since(self, timestamp: int) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE COALESCE(registered_at, updated_at) >= ?",
            (timestamp,),
        )
        row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def get_users_by_role(self, role: "Role | str") -> list[dict[str, Any]]:
        value = role.value if hasattr(role, "value") else str(role)
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE role=? ORDER BY user_id", (value,)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def role_counts(self) -> dict[str, int]:
        cursor = await self.conn.execute(
            "SELECT role, COUNT(*) AS cnt FROM users GROUP BY role"
        )
        return {row["role"]: int(row["cnt"]) for row in await cursor.fetchall()}

    async def all_user_ids(self) -> list[int]:
        cursor = await self.conn.execute("SELECT user_id FROM users ORDER BY user_id")
        return [int(row["user_id"]) for row in await cursor.fetchall()]

    async def list_staff_users(self) -> list[dict[str, Any]]:
        staff = tuple(
            role.value
            for role in (
                Role.OWNER,
                Role.ADMIN,
                Role.IVAN,
                Role.TECH_ADMIN,
            )
        )
        placeholders = ", ".join("?" for _ in staff)
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM users
            WHERE role IN ({placeholders})
            ORDER BY CASE role
                WHEN 'OWNER' THEN 0
                WHEN 'ADMIN' THEN 1
                WHEN 'IVAN' THEN 2
                ELSE 3 END, user_id
            """,
            staff,
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_staff_ids(self) -> list[int]:
        return [int(row["user_id"]) for row in await self.list_staff_users()]

    async def list_user_offers_by_statuses(
        self,
        user_id: int,
        statuses: Iterable[str],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        statuses = tuple(statuses)
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM offers
            WHERE (buyer_id=? OR seller_id=?)
              AND status IN ({placeholders})
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, user_id, *statuses, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # --------------------------------------------------- журнал и служебное

    async def log_admin_action(
        self,
        admin_id: int,
        action: str,
        target_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO admin_log(admin_id, action, target_id, details, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                admin_id,
                action,
                target_id,
                json.dumps(details, ensure_ascii=False) if details else None,
                _now(),
            ),
        )

    async def list_admin_log(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM admin_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def add_error(
        self,
        source: str,
        message: str,
        traceback_text: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO error_log(source, message, traceback, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (source, message[:2000], (traceback_text or "")[:8000], _now()),
        )

    async def list_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM error_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def state_get(self, key: str) -> str | None:
        cursor = await self.conn.execute(
            "SELECT value FROM service_state WHERE key=?", (key,)
        )
        row = await cursor.fetchone()
        return None if row is None else row["value"]

    async def state_set(self, key: str, value: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO service_state(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (key, value, _now()),
        )

    async def state_delete(self, key: str) -> None:
        await self.conn.execute("DELETE FROM service_state WHERE key=?", (key,))

    async def maintenance_state(self) -> tuple[bool, int | None]:
        """Возвращает (включён ли режим, время окончания или None)."""
        mode = await self.state_get("maintenance_mode")
        if mode != "on":
            return False, None
        raw_until = await self.state_get("maintenance_until")
        try:
            until = int(raw_until) if raw_until else 0
        except ValueError:
            until = 0
        if until > 0 and until <= _now():
            await self.clear_maintenance()
            return False, None
        return True, until or None

    async def set_maintenance(
        self,
        *,
        until: int | None,
        reason: str | None = None,
        admin_id: int | None = None,
    ) -> None:
        await self.state_set("maintenance_mode", "on")
        await self.state_set("maintenance_until", str(until or 0))
        await self.state_set("maintenance_reason", reason or "")
        await self.state_set("maintenance_started_at", str(_now()))
        if admin_id is not None:
            await self.state_set("maintenance_by", str(admin_id))

    async def clear_maintenance(self) -> None:
        for key in (
            "maintenance_mode",
            "maintenance_until",
            "maintenance_reason",
            "maintenance_started_at",
            "maintenance_by",
        ):
            await self.state_delete(key)

    async def expire_maintenance(self) -> bool:
        """Автоматически снимает истёкший техрежим. True, если снял."""
        mode = await self.state_get("maintenance_mode")
        if mode != "on":
            return False
        raw_until = await self.state_get("maintenance_until")
        try:
            until = int(raw_until) if raw_until else 0
        except ValueError:
            until = 0
        if until > 0 and until <= _now():
            await self.clear_maintenance()
            return True
        return False

    async def setting_get(self, key: str, default: str | None = None) -> str | None:
        cursor = await self.conn.execute(
            "SELECT value FROM service_settings WHERE key=?", (key,)
        )
        row = await cursor.fetchone()
        return default if row is None else row["value"]

    async def setting_set(self, key: str, value: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO service_settings(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (key, value, _now()),
        )

    async def setting_delete(self, key: str) -> None:
        await self.conn.execute("DELETE FROM service_settings WHERE key=?", (key,))

    async def setting_all(self) -> dict[str, str]:
        cursor = await self.conn.execute(
            "SELECT key, value FROM service_settings ORDER BY key"
        )
        return {row["key"]: row["value"] for row in await cursor.fetchall()}

    async def add_notification(self, user_id: int, text: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO notifications(user_id, text, created_at)
            VALUES(?, ?, ?)
            """,
            (user_id, text[:4000], _now()),
        )

    async def list_notifications(
        self, user_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM notifications
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def mark_notifications_read(self, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0",
            (user_id,),
        )

    async def notifications_enabled(self, user_id: int) -> bool:
        cursor = await self.conn.execute(
            "SELECT enabled FROM notification_prefs WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        return True if row is None else bool(row["enabled"])

    async def set_notifications_enabled(self, user_id: int, enabled: bool) -> None:
        await self.conn.execute(
            """
            INSERT INTO notification_prefs(user_id, enabled, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                enabled=excluded.enabled,
                updated_at=excluded.updated_at
            """,
            (user_id, 1 if enabled else 0, _now()),
        )

    async def general_stats(self) -> dict[str, Any]:
        stats = await self.stats()
        cursor = await self.conn.execute("SELECT COUNT(*) AS cnt FROM offers")
        total_row = await cursor.fetchone()
        cursor = await self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS amount FROM offers WHERE status=?",
            (OfferStatus.COMPLETED.value,),
        )
        completed_amount = await cursor.fetchone()
        active_statuses = (
            OfferStatus.PENDING.value,
            OfferStatus.ACCEPTED.value,
            OfferStatus.AWAITING_PAYMENT.value,
            OfferStatus.PAID.value,
            OfferStatus.TRANSFERRING.value,
            OfferStatus.NFT_TRANSFERRED.value,
            OfferStatus.PAYOUT_PENDING.value,
            OfferStatus.DISPUTED.value,
        )
        placeholders = ", ".join("?" for _ in active_statuses)
        cursor = await self.conn.execute(
            f"SELECT COUNT(*) AS cnt FROM offers WHERE status IN ({placeholders})",
            active_statuses,
        )
        active_row = await cursor.fetchone()
        day_start = _now() - 86400
        return {
            "users": await self.count_users(),
            "users_today": await self.count_users_since(day_start),
            "roles": await self.role_counts(),
            "offers": int(total_row["cnt"]) if total_row else 0,
            "offers_by_status": stats,
            "active": int(active_row["cnt"]) if active_row else 0,
            "completed": int(stats.get(OfferStatus.COMPLETED.value, 0)),
            "completed_amount": int(completed_amount["amount"]) if completed_amount else 0,
        }

    async def all_offers_by_status(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT status, COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS amount
            FROM offers
            GROUP BY status
            ORDER BY status
            """
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def backup_to(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        destination = await aiosqlite.connect(path)
        try:
            await self.conn.backup(destination)
        finally:
            await destination.close()

    async def create_offer(
        self,
        *,
        group_chat_id: int,
        buyer_id: int,
        buyer_username: str | None,
        buyer_name: str,
        seller_id: int | None,
        seller_username: str | None,
        seller_name: str | None,
        nft_url: str,
        nft_slug: str,
        nft_title: str,
        nft_image_url: str | None,
        nft_description: str | None,
        nft_owner_label: str | None,
        amount: int,
        language: str = 'ru',
        expires_at: int,
    ) -> int:
        now = _now()
        cursor = await self.conn.execute(
            """
            INSERT INTO offers(
                group_chat_id, buyer_id, buyer_username, buyer_name,
                seller_id, seller_username, seller_name,
                nft_url, nft_slug, nft_title, nft_image_url, nft_description,
                nft_owner_label, language, amount, status, created_at, expires_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_chat_id,
                buyer_id,
                buyer_username,
                buyer_name,
                seller_id,
                seller_username,
                seller_name,
                nft_url,
                nft_slug,
                nft_title,
                nft_image_url,
                nft_description,
                nft_owner_label,
                language,
                amount,
                OfferStatus.PENDING.value,
                now,
                expires_at,
                now,
            ),
        )
        return int(cursor.lastrowid)

    async def set_inline_message(self, offer_id: int, inline_message_id: str) -> None:
        await self.conn.execute(
            """
            UPDATE offers
            SET inline_message_id=?, updated_at=?
            WHERE id=?
            """,
            (inline_message_id, _now(), offer_id),
        )
        await self.conn.execute(
            """
            UPDATE offers
            SET group_message_id=?, card_kind=?, updated_at=?
            WHERE id=?
            """,
            (message_id, card_kind, _now(), offer_id),
        )

    async def get_offer(self, offer_id: int) -> dict[str, Any] | None:
        cursor = await self.conn.execute("SELECT * FROM offers WHERE id=?", (offer_id,))
        return _row_to_dict(await cursor.fetchone())

    async def update_offer(self, offer_id: int, **fields: Any) -> bool:
        unknown = set(fields) - _ALLOWED_OFFER_FIELDS
        if unknown:
            raise ValueError(f"Недопустимые поля offers: {unknown}")
        if not fields:
            return False
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{name}=?" for name in fields)
        values = list(fields.values()) + [offer_id]
        cursor = await self.conn.execute(
            f"UPDATE offers SET {assignments} WHERE id=?", values
        )
        return cursor.rowcount == 1

    async def transition(
        self,
        offer_id: int,
        from_statuses: Iterable[str],
        to_status: str,
        *,
        require_unexpired: bool = False,
        **fields: Any,
    ) -> bool:
        unknown = set(fields) - _ALLOWED_OFFER_FIELDS
        if unknown:
            raise ValueError(f"Недопустимые поля offers: {unknown}")
        statuses = tuple(from_statuses)
        if not statuses:
            return False

        updates: dict[str, Any] = {
            "status": to_status,
            "updated_at": _now(),
            **fields,
        }
        assignments = ", ".join(f"{name}=?" for name in updates)
        placeholders = ", ".join("?" for _ in statuses)
        sql = f"UPDATE offers SET {assignments} WHERE id=? AND status IN ({placeholders})"
        params: list[Any] = list(updates.values()) + [offer_id, *statuses]
        if require_unexpired:
            sql += " AND expires_at > ?"
            params.append(_now())
        cursor = await self.conn.execute(sql, params)
        return cursor.rowcount == 1

    async def bind_seller(
        self,
        offer_id: int,
        seller_id: int,
        seller_username: str | None,
        seller_name: str | None,
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE offers
            SET seller_id=?,
                seller_username=COALESCE(?, seller_username),
                seller_name=COALESCE(?, seller_name),
                updated_at=?
            WHERE id=? AND (seller_id IS NULL OR seller_id=?)
            """,
            (seller_id, seller_username, seller_name, _now(), offer_id, seller_id),
        )
        return cursor.rowcount == 1

    async def set_payment_pending(
        self,
        offer_id: int,
        nonce: str,
        invoice_url: str,
        payment_due_at: int,
    ) -> bool:
        return await self.transition(
            offer_id,
            {OfferStatus.ACCEPTED.value},
            OfferStatus.AWAITING_PAYMENT.value,
            payment_nonce=nonce,
            invoice_url=invoice_url,
            payment_due_at=payment_due_at,
            seller_confirmed_at=_now(),
        )

    async def mark_paid(
        self,
        offer_id: int,
        buyer_id: int,
        amount: int,
        nonce: str,
        charge_id: str,
        provider_charge_id: str | None,
        paid_amount: int,
    ) -> bool:
        now = _now()
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await self.conn.execute(
                """
                INSERT OR IGNORE INTO payment_charges(
                    charge_id, offer_id, user_id, amount, created_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (charge_id, offer_id, buyer_id, paid_amount, now),
            )
            if cursor.rowcount != 1:
                await self.conn.execute("ROLLBACK")
                return False

            cursor = await self.conn.execute(
                """
                UPDATE offers
                SET status=?,
                    paid_at=?,
                    paid_amount=?,
                    payment_charge_id=?,
                    payment_provider_charge_id=?,
                    updated_at=?
                WHERE id=?
                  AND status=?
                  AND buyer_id=?
                  AND amount=?
                  AND payment_nonce=?
                  AND paid_at IS NULL
                """,
                (
                    OfferStatus.PAID.value,
                    now,
                    paid_amount,
                    charge_id,
                    provider_charge_id,
                    now,
                    offer_id,
                    OfferStatus.AWAITING_PAYMENT.value,
                    buyer_id,
                    amount,
                    nonce,
                ),
            )
            if cursor.rowcount != 1:
                await self.conn.execute("ROLLBACK")
                return False
            await self.conn.execute("COMMIT")
            return True
        except Exception:
            await self.conn.execute("ROLLBACK")
            raise

    async def mark_nft_transferred(
        self,
        offer_id: int,
        *,
        method: str,
        transfer_id: str | None = None,
        transfer_error: str | None = None,
        verified: bool = False,
        verification_method: str | None = None,
    ) -> bool:
        now = _now()
        return await self.transition(
            offer_id,
            {
                OfferStatus.PAID.value,
                OfferStatus.TRANSFERRING.value,
                OfferStatus.DISPUTED.value,
            },
            OfferStatus.NFT_TRANSFERRED.value,
            nft_sent_at=now,
            nft_transfer_mode=method,
            nft_transfer_id=transfer_id,
            nft_transfer_error=transfer_error,
            nft_verified_at=now if verified else None,
            nft_verification_method=verification_method if verified else None,
        )

    async def mark_nft_verified(
        self, offer_id: int, method: str
    ) -> bool:
        return await self.update_offer(
            offer_id,
            nft_verified_at=_now(),
            nft_verification_method=method,
        )

    async def mark_payout_pending(self, offer_id: int) -> bool:
        return await self.transition(
            offer_id,
            {OfferStatus.NFT_TRANSFERRED.value},
            OfferStatus.PAYOUT_PENDING.value,
        )

    async def mark_completed(
        self, offer_id: int, reference: str, admin_id: int
    ) -> bool:
        return await self.transition(
            offer_id,
            {OfferStatus.PAYOUT_PENDING.value, OfferStatus.DISPUTED.value},
            OfferStatus.COMPLETED.value,
            completed_at=_now(),
            closed_at=_now(),
            payout_reference=reference,
            payout_at=_now(),
            payout_by=admin_id,
        )

    async def mark_refunded(self, offer_id: int) -> bool:
        return await self.transition(
            offer_id,
            {
                OfferStatus.AWAITING_PAYMENT.value,
                OfferStatus.PAID.value,
                OfferStatus.TRANSFERRING.value,
                OfferStatus.NFT_TRANSFERRED.value,
                OfferStatus.PAYOUT_PENDING.value,
                OfferStatus.DISPUTED.value,
            },
            OfferStatus.REFUNDED.value,
            closed_at=_now(),
        )

    async def mark_disputed(self, offer_id: int) -> bool:
        return await self.transition(
            offer_id,
            {
                OfferStatus.PAID.value,
                OfferStatus.TRANSFERRING.value,
                OfferStatus.NFT_TRANSFERRED.value,
                OfferStatus.PAYOUT_PENDING.value,
            },
            OfferStatus.DISPUTED.value,
        )

    async def mark_cancelled(
        self, offer_id: int, from_statuses: Iterable[str], reason: str
    ) -> bool:
        return await self.transition(
            offer_id,
            from_statuses,
            OfferStatus.CANCELLED.value,
            closed_at=_now(),
            cancel_reason=reason,
        )

    async def mark_expired(self, offer_id: int) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE offers
            SET status=?, closed_at=?, updated_at=?
            WHERE id=? AND status=? AND expires_at <= ?
            """,
            (
                OfferStatus.EXPIRED.value,
                _now(),
                _now(),
                offer_id,
                OfferStatus.PENDING.value,
                _now(),
            ),
        )
        return cursor.rowcount == 1

    async def due_expirations(self, now: int | None = None) -> list[dict[str, Any]]:
        now = now or _now()
        cursor = await self.conn.execute(
            """
            SELECT * FROM offers
            WHERE status=? AND expires_at <= ?
            ORDER BY id ASC
            LIMIT 100
            """,
            (OfferStatus.PENDING.value, now),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def pending_offers(self, limit: int = 500) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM offers
            WHERE status=?
            ORDER BY expires_at ASC
            LIMIT ?
            """,
            (OfferStatus.PENDING.value, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def due_payment_timeouts(self, now: int | None = None) -> list[dict[str, Any]]:
        now = now or _now()
        cursor = await self.conn.execute(
            """
            SELECT * FROM offers
            WHERE status=? AND payment_due_at IS NOT NULL AND payment_due_at <= ?
            ORDER BY id ASC
            LIMIT 100
            """,
            (OfferStatus.AWAITING_PAYMENT.value, now),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def find_active_offer(
        self,
        *,
        buyer_id: int,
        nft_slug: str,
        seller_id: int | None,
        seller_username: str | None,
    ) -> dict[str, Any] | None:
        statuses = (
            OfferStatus.PENDING.value,
            OfferStatus.ACCEPTED.value,
            OfferStatus.AWAITING_PAYMENT.value,
            OfferStatus.PAID.value,
            OfferStatus.TRANSFERRING.value,
            OfferStatus.NFT_TRANSFERRED.value,
            OfferStatus.PAYOUT_PENDING.value,
            OfferStatus.DISPUTED.value,
        )
        placeholders = ", ".join("?" for _ in statuses)
        if seller_id is not None:
            cursor = await self.conn.execute(
                f"""
                SELECT * FROM offers
                WHERE buyer_id=? AND nft_slug=? AND seller_id=?
                  AND status IN ({placeholders})
                ORDER BY id DESC LIMIT 1
                """,
                (buyer_id, nft_slug, seller_id, *statuses),
            )
        elif seller_username:
            cursor = await self.conn.execute(
                f"""
                SELECT * FROM offers
                WHERE buyer_id=? AND nft_slug=? AND lower(seller_username)=lower(?)
                  AND status IN ({placeholders})
                ORDER BY id DESC LIMIT 1
                """,
                (buyer_id, nft_slug, seller_username, *statuses),
            )
        else:
            return None
        return _row_to_dict(await cursor.fetchone())

    async def find_active_nft_offer(
        self,
        *,
        nft_slug: str,
        seller_id: int | None,
        seller_username: str | None,
        exclude_offer_id: int,
    ) -> dict[str, Any] | None:
        statuses = (
            OfferStatus.ACCEPTED.value,
            OfferStatus.AWAITING_PAYMENT.value,
            OfferStatus.PAID.value,
            OfferStatus.TRANSFERRING.value,
            OfferStatus.NFT_TRANSFERRED.value,
            OfferStatus.PAYOUT_PENDING.value,
            OfferStatus.DISPUTED.value,
        )
        placeholders = ", ".join("?" for _ in statuses)
        if seller_id is not None and seller_username:
            condition = "(seller_id=? OR lower(seller_username)=lower(?))"
            params: tuple[Any, ...] = (seller_id, seller_username)
        elif seller_id is not None:
            condition = "seller_id=?"
            params = (seller_id,)
        elif seller_username:
            condition = "lower(seller_username)=lower(?)"
            params = (seller_username,)
        else:
            return None
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM offers
            WHERE nft_slug=? AND id<>? AND {condition}
              AND status IN ({placeholders})
            ORDER BY id DESC LIMIT 1
            """,
            (nft_slug, exclude_offer_id, *params, *statuses),
        )
        return _row_to_dict(await cursor.fetchone())

    async def list_user_offers(
        self, user_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM offers
            WHERE buyer_id=? OR seller_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, user_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_by_statuses(
        self, statuses: Iterable[str], limit: int = 30
    ) -> list[dict[str, Any]]:
        statuses = tuple(statuses)
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM offers
            WHERE status IN ({placeholders})
            ORDER BY id DESC LIMIT ?
            """,
            (*statuses, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def stats(self) -> dict[str, int]:
        result: dict[str, int] = {}
        cursor = await self.conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM offers GROUP BY status"
        )
        for row in await cursor.fetchall():
            result[row["status"]] = int(row["cnt"])
        return result

    async def charge_exists(self, charge_id: str) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM payment_charges WHERE charge_id=? LIMIT 1",
            (charge_id,),
        )
        return await cursor.fetchone() is not None

    async def claim_refund(
        self,
        *,
        charge_id: str,
        offer_id: int | None,
        user_id: int,
        amount: int | None,
        reason: str,
    ) -> bool:
        """Атомарно резервирует возврат, чтобы не вернуть Stars дважды."""
        cursor = await self.conn.execute(
            """
            INSERT OR IGNORE INTO refunds(
                charge_id, offer_id, user_id, amount, reason, created_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (charge_id, offer_id, user_id, amount, reason[:300], _now()),
        )
        return cursor.rowcount == 1

    async def release_refund(self, charge_id: str) -> None:
        """Снимает резерв, если Telegram не выполнил возврат."""
        await self.conn.execute("DELETE FROM refunds WHERE charge_id=?", (charge_id,))

    async def add_event(
        self,
        offer_id: int,
        actor_id: int | None,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO events(offer_id, actor_id, action, details, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                offer_id,
                actor_id,
                action,
                json.dumps(details, ensure_ascii=False) if details else None,
                _now(),
            ),
        )

    async def get_events(
        self, offer_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM events
            WHERE offer_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (offer_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def save_business_connection(
        self,
        *,
        user_id: int,
        connection_id: str,
        user_chat_id: int | None,
        is_enabled: bool,
        rights: dict[str, Any] | None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO business_connections(
                user_id, connection_id, user_chat_id, is_enabled, rights_json, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                connection_id=excluded.connection_id,
                user_chat_id=excluded.user_chat_id,
                is_enabled=excluded.is_enabled,
                rights_json=excluded.rights_json,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                connection_id,
                user_chat_id,
                1 if is_enabled else 0,
                json.dumps(rights, ensure_ascii=False) if rights else None,
                _now(),
            ),
        )

    async def disable_business_connection(self, connection_id: str) -> None:
        await self.conn.execute(
            """
            UPDATE business_connections
            SET is_enabled=0, updated_at=?
            WHERE connection_id=?
            """,
            (_now(), connection_id),
        )

    async def get_business_connection(
        self, user_id: int
    ) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT * FROM business_connections WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("rights_json"):
            try:
                result["rights"] = json.loads(result["rights_json"])
            except json.JSONDecodeError:
                result["rights"] = {}
        else:
            result["rights"] = {}
        return result
