"""Дополнительные команды OWNER и ADMIN."""

from __future__ import annotations

import html
import time
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from access import get_actor, require_message_permission, role_of
from config import Settings
from database import Database
from roles import ALL_ROLES, Permission, Role, has_permission, parse_role, role_label

router = Router(name="extra_admin")

def _esc(v):
    return html.escape(str(v), quote=True)


@router.message(Command("roleinfo"))
async def cmd_roleinfo(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_ROLES, private_only=True):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /roleinfo ROLE")
        return
    role = parse_role(parts[1])
    if role is None:
        await message.reply("Неизвестная роль. Доступны: USER, TECH ADMIN, ADMIN, OWNER, SKAM, WORKER, IVAN.")
        return
    perms = [p.value for p in Permission if has_permission(role, p)]
    await message.reply(
        f"<b>Роль {role_label(role)}</b>\n\n"
        f"Прав: {len(perms)}\n"
        f"Команды: {len(__import__('roles').commands_for_role(role))}\n\n"
        f"Права: {', '.join(perms[:15])}{'...' if len(perms) > 15 else ''}"
    )


@router.message(Command("roleusers"))
async def cmd_roleusers(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_ROLES, private_only=True):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /roleusers ROLE")
        return
    role = parse_role(parts[1])
    if role is None:
        await message.reply("Неизвестная роль.")
        return
    users = await db.get_users_by_role(role) if hasattr(db, "get_users_by_role") else []
    if not users:
        # fallback: count
        counts = await db.role_counts()
        await message.reply(f"Роль {role_label(role)}: {counts.get(role.value, 0)} пользователей.")
        return
    lines = [f"<b>Пользователи с ролью {role_label(role)}</b>", ""]
    for u in users[:20]:
        uname = ("@" + u["username"]) if u.get("username") else str(u["user_id"])
        lines.append(f"• {uname} (<code>{u['user_id']}</code>)")
    await message.reply("\n".join(lines))


@router.message(Command("permissions"))
async def cmd_permissions(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_ROLES, private_only=True):
        return
    record = await get_actor(db, settings, message.from_user)
    role = role_of(record)
    perms = [p.value for p in Permission if has_permission(role, p)]
    await message.reply(
        f"<b>Ваши права ({role.value})</b>\n\n" + "\n".join(f"• {p}" for p in perms)
    )


@router.message(Command("botinfo"))
async def cmd_botinfo(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    me = await message.bot.get_me()
    await message.reply(
        "<b>Информация о боте</b>\n\n"
        f"Имя: {_esc(me.first_name)}\n"
        f"Username: @{me.username}\n"
        f"ID: {me.id}\n"
        f"Может вступать в группы: {me.can_join_groups}\n"
        f"Поддерживает inline: {getattr(me, 'supports_inline_queries', 'N/A')}\n"
        f"Владелец: {', '.join(str(i) for i in sorted(settings.owner_ids)) or 'не задан'}"
    )


@router.message(Command("botstats"))
async def cmd_botstats(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_FULL_STATS, private_only=True):
        return
    stats = await db.general_stats()
    await message.reply(
        "<b>Статистика бота</b>\n\n"
        f"Пользователей: {stats['users']}\n"
        f"Сделок: {stats['offers']}\n"
        f"Активных: {stats['active']}\n"
        f"Завершено: {stats['completed']}\n"
        f"Оборот: {stats['completed_amount']} Stars"
    )


@router.message(Command("botmode"))
async def cmd_botmode(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_MAINTENANCE, private_only=True):
        return
    active, until = await db.maintenance_state()
    await message.reply(
        f"Режим бота: {'техрежим' if active else 'нормальный'}\n"
        f"Оплата: {'включена' if settings.payments_available else 'выключена'}"
    )


@router.message(Command("maintenance_info"))
async def cmd_maintenance_info(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_MAINTENANCE, private_only=True):
        return
    active, until = await db.maintenance_state()
    if active:
        finish = datetime.fromtimestamp(until, tz=settings.tz).strftime("%d.%m.%Y %H:%M") if until else "без срока"
        await message.reply(f"Техрежим: включён. До: {finish}")
    else:
        await message.reply("Техрежим: выключен.")


@router.message(Command("backup_info", "backupstatus"))
async def cmd_backup_info(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.BACKUP, private_only=True):
        return
    import os
    backup_dir = settings.database_path.parent.parent / "backups"
    files = list(backup_dir.glob("backup_*.sqlite3")) if backup_dir.exists() else []
    await message.reply(
        "<b>Резервные копии</b>\n\n"
        f"Директория: {_esc(backup_dir)}\n"
        f"Количество: {len(files)}\n"
        + (f"Последняя: {files[-1].name}" if files else "Копий нет.")
    )


@router.message(Command("useractivity", "userdeals", "useroffers", "userhistory"))
async def cmd_useractivity(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_USERS, private_only=True):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /useractivity ID")
        return
    uid = int(parts[1].strip())
    record = await db.get_user(uid)
    if record is None:
        await message.reply("Пользователь не найден.")
        return
    completed = await db.count_completed_deals(uid)
    await message.reply(
        f"<b>Активность пользователя {uid}</b>\n\n"
        f"Роль: {role_of(record).value}\n"
        f"Завершённые сделки: {completed}\n"
        f"Бан: {'да' if record.get('is_banned') else 'нет'}"
    )


@router.message(Command("userrole"))
async def cmd_userrole(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_ROLES, private_only=True):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /userrole ID")
        return
    uid = int(parts[1].strip())
    record = await db.get_user(uid)
    if record is None:
        await message.reply("Пользователь не найден.")
        return
    await message.reply(f"Пользователь {uid}: роль {role_of(record).value}")


@router.message(Command("usernote", "usernotes"))
async def cmd_usernote(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_ROLES, private_only=True):
        return
    await message.reply("Заметки пользователей: функция в разработке. Данные хранятся в admin_log.")


@router.message(Command("topusers"))
async def cmd_topusers(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    await message.reply("Топ пользователей: используйте /stats для общей статистики.")


@router.message(Command("newusers"))
async def cmd_newusers(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    today = await db.count_users_since(int(time.time()) - 86400)
    await message.reply(f"Новых пользователей за 24 часа: {today}")


@router.message(Command("todaystats", "weekstats", "monthstats"))
async def cmd_periodstats(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    days = 1 if "today" in (message.text or "") else (7 if "week" in (message.text or "") else 30)
    since = int(time.time()) - days * 86400
    users = await db.count_users_since(since)
    await message.reply(f"За {days} дн.: новых пользователей {users}.")


@router.message(Command("searchuser"))
async def cmd_searchuser(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_USERS, private_only=True):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /searchuser ID_ИЛИ_@username")
        return
    from access import _resolve_target if False else None
    target = None
    raw = parts[1].strip()
    if raw.isdigit():
        target = await db.get_user(int(raw))
    elif raw.startswith("@"):
        target = await db.get_user_by_username(raw)
    if target is None:
        await message.reply("Пользователь не найден.")
        return
    await message.reply(
        f"ID: {target['user_id']}\n"
        f"Username: {target.get('username') or '—'}\n"
        f"Роль: {role_of(target).value}\n"
        f"Бан: {'да' if target.get('is_banned') else 'нет'}"
    )


@router.message(Command("searchdeal", "offersearch", "offerinfo"))
async def cmd_searchdeal(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /searchdeal ID")
        return
    offer = await db.get_offer(int(parts[1].strip()))
    if offer is None:
        await message.reply("Сделка не найдена.")
        return
    await message.reply(
        f"Сделка #{offer['id']}\n"
        f"Статус: {offer['status']}\n"
        f"Сумма: {offer['amount']} Stars\n"
        f"Покупатель: {offer['buyer_id']}\n"
        f"Продавец: {offer.get('seller_id') or '—'}"
    )


@router.message(Command("offerstats", "offerlist"))
async def cmd_offerstats(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    offers = await db.all_offers_by_status()
    lines = ["<b>Статистика оферов</b>", ""]
    for row in offers:
        lines.append(f"{row['status']}: {row['cnt']} (на {row['amount']} Stars)")
    await message.reply("\n".join(lines) if offers else "Оферов нет.")


@router.message(Command("offerexpire"))
async def cmd_offerexpire(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_MAINTENANCE, private_only=True):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Использование: /offerexpire ID")
        return
    offer_id = int(parts[1].strip())
    if await db.mark_expired(offer_id):
        await message.reply(f"Офер #{offer_id} помечен как истёкший.")
    else:
        await message.reply(f"Не удалось пометить офер #{offer_id}.")


@router.message(Command("broadcast_all", "broadcast_preview", "broadcast_cancel"))
async def cmd_broadcast_extra(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.BROADCAST, private_only=True):
        return
    await message.reply("Используйте /broadcast для рассылки. Предпросмотр и отмена — в разработке.")


@router.message(Command("exportstats", "broadcast_stats"))
async def cmd_exportstats(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    stats = await db.general_stats()
    await message.reply(
        f"Экспорт статистики:\\n"
        f"Пользователей: {stats['users']}\\n"
        f"Сделок: {stats['offers']}\\n"
        f"Завершено: {stats['completed']}"
    )


@router.message(Command("activity", "referrals"))
async def cmd_activity(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_STATS, private_only=True):
        return
    await message.reply("Активность и рефералы: используйте /stats для общей статистики.")


@router.message(Command("feature", "featurelist"))
async def cmd_feature(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_MAINTENANCE, private_only=True):
        return
    await message.reply("Управление функциями: в разработке.")


@router.message(Command("antispam", "autodelete", "deletetime", "cleanbot", "offerdelete", "offerpreview", "offerpause", "offerresume", "offerlimit", "offersettings"))
async def cmd_offer_mgmt(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_MAINTENANCE, private_only=True):
        return
    cmd = (message.text or "").split()[0].lower().lstrip("/")
    await message.reply(f"Команда /{cmd}: функция в разработке. Настройки хранятся в service_settings.")


@router.message(Command("restart_info", "shutdown_info", "ownerpanel"))
async def cmd_owner_panel(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_MAINTENANCE, private_only=True):
        return
    await message.reply(
        "Панель владельца.\\n"
        "Перезапуск: через Render Dashboard.\\n"
        "Выключение: /zakrit (12 часов).\\n"
        "Все команды: /comand"
    )


@router.message(Command("inbox", "achievements"))
async def cmd_inbox(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_PROFILE):
        return
    await message.reply("Центр уведомлений и достижения: в разработке. Уведомления: /notifications")
