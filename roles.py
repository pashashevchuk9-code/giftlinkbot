"""Роли, права и списки команд.

Ровно семь ролей. Роль хранится в SQLite, OWNER дополнительно закреплён
за ID из конфигурации (OWNER_ID / OWNER_IDS).
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    USER = "USER"
    TECH_ADMIN = "TECH ADMIN"
    ADMIN = "ADMIN"
    OWNER = "OWNER"
    SKAM = "SKAM"
    WORKER = "WORKER"
    IVAN = "IVAN"


# Отображаемые названия.
ROLE_LABELS: dict[Role, str] = {
    Role.USER: "USER",
    Role.TECH_ADMIN: "TECH ADMIN",
    Role.ADMIN: "ADMIN",
    Role.OWNER: "OWNER",
    Role.SKAM: "SKAM",
    Role.WORKER: "WORKER",
    Role.IVAN: "IVAN (Иван)",
}

_ROLE_ALIASES: dict[str, Role] = {
    "user": Role.USER,
    "пользователь": Role.USER,
    "worker": Role.WORKER,
    "работник": Role.WORKER,
    "рабочий": Role.WORKER,
    "tech admin": Role.TECH_ADMIN,
    "tech_admin": Role.TECH_ADMIN,
    "tech-admin": Role.TECH_ADMIN,
    "techadmin": Role.TECH_ADMIN,
    "тех админ": Role.TECH_ADMIN,
    "тех. админ": Role.TECH_ADMIN,
    "техадмин": Role.TECH_ADMIN,
    "admin": Role.ADMIN,
    "админ": Role.ADMIN,
    "администратор": Role.ADMIN,
    "owner": Role.OWNER,
    "владелец": Role.OWNER,
    "skam": Role.SKAM,
    "скам": Role.SKAM,
    "ivan": Role.IVAN,
    "иван": Role.IVAN,
}


def parse_role(raw: str | None) -> Role | None:
    """Разбирает роль из команды, включая русские названия."""
    if not raw:
        return None
    value = " ".join(raw.strip().replace("_", " ").split()).lower()
    return _ROLE_ALIASES.get(value)


def role_from_db(value: str | None) -> Role:
    """Безопасно превращает значение из БД в Role (по умолчанию USER)."""
    if not value:
        return Role.USER
    try:
        return Role(value)
    except ValueError:
        return parse_role(value) or Role.USER


def role_label(role: Role) -> str:
    return ROLE_LABELS.get(role, role.value)


class Permission(str, Enum):
    # Пользовательские.
    CREATE_OFFER = "create_offer"
    VIEW_OWN_OFFERS = "view_own_offers"
    VIEW_HISTORY = "view_history"
    VIEW_PROFILE = "view_profile"
    USE_STANDARD = "use_standard"
    MANAGE_NOTIFICATIONS = "manage_notifications"
    VIEW_RULES = "view_rules"
    VIEW_SUPPORT = "view_support"
    # TECH ADMIN.
    VIEW_USERS = "view_users"
    BAN_USERS = "ban_users"
    VIEW_ERRORS = "view_errors"
    VIEW_ACTIVE = "view_active"
    MANAGE_RESTRICTIONS = "manage_restrictions"
    # ADMIN / IVAN.
    VIEW_STATS = "view_stats"
    VIEW_USERS_COUNT = "view_users_count"
    VIEW_DEAL_STATS = "view_deal_stats"
    BROADCAST = "broadcast"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_REFUNDS = "manage_refunds"
    # OWNER.
    MANAGE_ROLES = "manage_roles"
    VIEW_FULL_STATS = "view_full_stats"
    MANAGE_TECH = "manage_tech"
    BACKUP = "backup"
    MANAGE_MAINTENANCE = "manage_maintenance"
    ALL_COMMANDS = "all_commands"


BASE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.CREATE_OFFER,
        Permission.VIEW_OWN_OFFERS,
        Permission.VIEW_HISTORY,
        Permission.VIEW_PROFILE,
        Permission.USE_STANDARD,
        Permission.MANAGE_NOTIFICATIONS,
        Permission.VIEW_RULES,
        Permission.VIEW_SUPPORT,
    }
)

TECH_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_USERS,
        Permission.BAN_USERS,
        Permission.VIEW_ERRORS,
        Permission.VIEW_ACTIVE,
        Permission.MANAGE_RESTRICTIONS,
    }
)

ADMIN_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_STATS,
        Permission.VIEW_USERS_COUNT,
        Permission.VIEW_DEAL_STATS,
        Permission.BROADCAST,
        Permission.MANAGE_SETTINGS,
        Permission.MANAGE_REFUNDS,
    }
)

OWNER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.MANAGE_ROLES,
        Permission.VIEW_FULL_STATS,
        Permission.MANAGE_TECH,
        Permission.BACKUP,
        Permission.MANAGE_MAINTENANCE,
        Permission.ALL_COMMANDS,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: BASE_PERMISSIONS,
    Role.WORKER: BASE_PERMISSIONS,
    Role.TECH_ADMIN: BASE_PERMISSIONS | TECH_PERMISSIONS,
    Role.ADMIN: BASE_PERMISSIONS | ADMIN_PERMISSIONS,
    # IVAN получает только права ADMIN, без TECH ADMIN и без OWNER.
    Role.IVAN: BASE_PERMISSIONS | ADMIN_PERMISSIONS,
    Role.OWNER: (
        BASE_PERMISSIONS | TECH_PERMISSIONS | ADMIN_PERMISSIONS | OWNER_PERMISSIONS
    ),
    Role.SKAM: frozenset(),
}

# Роли, которым разрешены административные действия (не пользовательские).
STAFF_ROLES: frozenset[Role] = frozenset(
    {Role.TECH_ADMIN, Role.ADMIN, Role.OWNER, Role.IVAN}
)

# Роли, которые могут выполнять денежные операции (выплаты, возвраты).
PAYMENT_ADMIN_ROLES: frozenset[Role] = frozenset(
    {Role.ADMIN, Role.OWNER, Role.IVAN}
)

# Роли, которые видят сделки всех пользователей.
DEAL_VIEWER_ROLES: frozenset[Role] = frozenset(
    {Role.TECH_ADMIN, Role.ADMIN, Role.OWNER, Role.IVAN}
)


def has_permission(role: Role, permission: Permission) -> bool:
    """Проверка права. SKAM всегда запрещён, OWNER всегда разрешён."""
    if role is Role.SKAM:
        return False
    if role is Role.OWNER:
        return True
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def is_staff(role: Role) -> bool:
    return role in STAFF_ROLES


# ------------------------------------------------------------------ команды

USER_COMMANDS: list[tuple[str, str]] = [
    ("/start", "главное меню"),
    ("/profile", "мой профиль"),
    ("/deals", "мои предложения"),
    ("/history", "история сделок"),
    ("/rules", "правила обмена"),
    ("/comand", "список команд"),
]


TECH_COMMANDS: list[tuple[str, str]] = [
    ("/userinfo", "информация о пользователе"),
    ("/ban", "заблокировать пользователя"),
    ("/unban", "разблокировать пользователя"),
    ("/warnings", "предупреждения пользователя"),
    ("/warn", "выдать предупреждение или временное ограничение"),
    ("/untimeout", "снять временное ограничение"),
    ("/active", "активные сделки"),
    ("/errors", "технические ошибки"),
    ("/techpanel", "техническая панель"),
    ("/health", "проверка здоровья бота"),
    ("/serverinfo", "информация о сервере"),
    ("/uptime", "время работы"),
    ("/latency", "задержки БД и API"),
    ("/runtime", "версии зависимостей"),
    ("/webhookinfo", "информация о webhook"),
    ("/webhookcheck", "проверка webhook"),
    ("/botapi", "информация о Bot API"),
    ("/inlinecheck", "проверка inline mode"),
    ("/updates", "последние обновления"),
    ("/callbackstats", "статистика callback"),
    ("/dbinfo", "информация о базе данных"),
    ("/dbtables", "таблицы БД"),
    ("/dbsize", "размер БД"),
    ("/dbcheck", "проверка БД"),
    ("/dberrors", "ошибки БД"),
    ("/dbquery", "безопасный SELECT-запрос"),
    ("/logs", "логи"),
    ("/errorsearch", "поиск ошибок"),
    ("/eventlog", "журнал событий"),
    ("/audit", "аудит"),
    ("/securitylog", "журнал безопасности"),
    ("/clearlogs", "очистка логов"),
    ("/queue", "очереди и задачи"),
    ("/notifications_stats", "статистика уведомлений"),
    ("/storageinfo", "хранилище"),
    ("/limits", "лимиты"),
    ("/usage", "использование"),
    ("/diagnostics", "диагностика"),
    ("/selftest", "самопроверка"),
    ("/configcheck", "проверка конфигурации"),
    ("/dependencycheck", "проверка зависимостей"),
    ("/securitycheck", "проверка безопасности"),
    ("/healthreport", "отчёт о здоровье"),
    ("/reporttech", "технический отчёт"),
    ("/performance", "производительность"),
    ("/traffic", "трафик"),
    ("/requests", "запросы"),
    ("/requeststats", "статистика запросов"),
    ("/errorstats", "статистика ошибок"),
    ("/workerstatus", "статус worker"),
]

ADMIN_COMMANDS: list[tuple[str, str]] = [
    ("/stats", "общая статистика"),
    ("/users", "количество пользователей"),
    ("/dealsstats", "статистика сделок"),
    ("/broadcast", "информационная рассылка"),
    ("/settings", "настройки сервиса"),
]

OWNER_COMMANDS: list[tuple[str, str]] = [
    ("/roles", "выдать роль пользователю (только OWNER)"),
    ("/setrole", "назначить роль пользователю"),
    ("/removerole", "снять дополнительную роль"),
    ("/admins", "список администраторов"),
    ("/backup", "резервная копия базы данных"),
    ("/maintenance", "включить или выключить технический режим"),
    ("/zakrit", "выключить бота на 12 часов"),
    ("/open", "досрочно включить бота"),
    ("/comand", "показать все команды всех ролей"),
]


def commands_for_role(role: Role) -> list[tuple[str, str]]:
    """Плоский список команд, доступных роли."""
    if role is Role.SKAM:
        return []
    if role is Role.OWNER:
        return _dedupe(USER_COMMANDS + TECH_COMMANDS + ADMIN_COMMANDS + OWNER_COMMANDS)
    if role is Role.TECH_ADMIN:
        return _dedupe(USER_COMMANDS + TECH_COMMANDS)
    if role is Role.WORKER:
        return list(WORKER_COMMANDS)
    if role in {Role.ADMIN, Role.IVAN}:
        return _dedupe(USER_COMMANDS + ADMIN_COMMANDS)
    return list(USER_COMMANDS)


def command_sections(role: Role) -> list[tuple[str, list[tuple[str, str]]]]:
    """Секции для /comand. OWNER видит все секции."""
    if role is Role.SKAM:
        return []
    if role is Role.OWNER:
        return [
            ("USER / WORKER", USER_COMMANDS),
            ("TECH ADMIN", TECH_COMMANDS),
            ("ADMIN / IVAN", ADMIN_COMMANDS),
            ("OWNER", OWNER_COMMANDS),
        ]
    if role is Role.TECH_ADMIN:
        return [("USER / WORKER", USER_COMMANDS), ("TECH ADMIN", TECH_COMMANDS)]
    if role is Role.WORKER:
        return [("USER", USER_COMMANDS), ("WORKER", WORKER_EXTRA_COMMANDS)]
    if role in {Role.ADMIN, Role.IVAN}:
        return [("USER / WORKER", USER_COMMANDS), ("ADMIN / IVAN", ADMIN_COMMANDS)]
    return [("USER / WORKER", USER_COMMANDS)]


def allowed_command_names(role: Role) -> frozenset[str]:
    return frozenset(name.lstrip("/") for name, _ in commands_for_role(role))


def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for name, description in items:
        if name in seen:
            continue
        seen.add(name)
        result.append((name, description))
    return result


ALL_ROLES: tuple[Role, ...] = (
    Role.USER,
    Role.TECH_ADMIN,
    Role.ADMIN,
    Role.OWNER,
    Role.SKAM,
    Role.WORKER,
    Role.IVAN,
)

WORKER_EXTRA_COMMANDS: list[tuple[str, str]] = [
    ("/workerpanel", "панель сотрудника"),
    ("/workerinfo", "информация о роли"),
    ("/workerstats", "статистика сотрудника"),
    ("/workerhistory", "история активности"),
    ("/workerhelp", "помощь сотруднику"),
]

WORKER_COMMANDS: list[tuple[str, str]] = _dedupe(USER_COMMANDS + WORKER_EXTRA_COMMANDS)

