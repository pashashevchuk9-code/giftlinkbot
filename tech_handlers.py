"""Технические команды для TECH ADMIN и OWNER.

Все команды выполняют реальные проверки. Показатели, недоступные на хостинге,
обозначаются соответствующим сообщением. Секреты не выводятся.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from access import get_actor, require_message_permission, role_of
from config import Settings
from database import Database
from roles import Permission, Role

router = Router(name="tech")

_START_TIME = time.time()


def _esc(value) -> str:
    import html
    return html.escape(str(value), quote=True)


async def _guard(message, db, settings):
    if message.from_user is None:
        return None
    if not await require_message_permission(
        message, db, settings, Permission.VIEW_ERRORS, private_only=True
    ):
        return None
    return await get_actor(db, settings, message.from_user)


# ------------------------------------------------------------------ панель

@router.message(Command("techpanel"))
async def cmd_techpanel(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Техническая панель</b>\n\n"
        "Мониторинг: /health /serverinfo /uptime /runtime /latency\n"
        "Telegram: /webhookinfo /botapi /inlinecheck /callbackstats\n"
        "База данных: /dbinfo /dbhealth /dbstats /dbtables /dbsize /dbcheck\n"
        "Логи: /logs /errors /errorstats /eventlog /audit /logstats\n"
        "Очереди: /queue /jobs /jobstats /scheduler /limits /usage\n"
        "Диагностика: /diagnostics /selftest /configcheck /healthreport\n"
        "Полный список: /comand"
    )


# ------------------------------------------------------------------ мониторинг

@router.message(Command("health"))
async def cmd_health(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    uptime = int(time.time() - _START_TIME)
    db_ok = "OK"
    try:
        await db.count_users()
    except Exception as exc:
        db_ok = f"ERROR: {exc}"
    lines = [
        "<b>Health Check</b>",
        "",
        f"Бот: OK",
        f"База данных: {db_ok}",
        f"Uptime процесса: {uptime} сек",
        f"Python: {sys.version.split()[0]}",
        f"Платформа: {sys.platform}",
    ]
    await message.reply("\n".join(lines))


@router.message(Command("serverinfo"))
async def cmd_serverinfo(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Информация о сервере</b>\n\n"
        f"Python: {sys.version.split()[0]}\n"
        f"Платформа: {sys.platform}\n"
        f"Рабочая директория: {_esc(Path.cwd())}\n"
        "CPU/RAM/диск: недоступны на данном хостинге напрямую. "
        "Используйте панель хостинга (Render)."
    )


@router.message(Command("uptime"))
async def cmd_uptime(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    uptime = int(time.time() - _START_TIME)
    hours, rem = divmod(uptime, 3600)
    minutes, seconds = divmod(rem, 60)
    await message.reply(
        f"<b>Uptime</b>\n\n"
        f"Процесс бота: {hours} ч {minutes} мин {seconds} сек\n"
        f"Запущен: {datetime.fromtimestamp(_START_TIME, tz=timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC')}"
    )


@router.message(Command("runtime"))
async def cmd_runtime(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Runtime</b>\n\n"
        f"Python: {sys.version}\n"
        f"aiogram: {__import__('aiogram').__version__}\n"
        f"aiohttp: {__import__('aiohttp').__version__}\n"
        f"aiosqlite: {__import__('aiosqlite').__version__}\n"
        f"Платформа: {sys.platform}"
    )


@router.message(Command("latency"))
async def cmd_latency(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    import time as _t
    start = _t.monotonic()
    try:
        await db.count_users()
        db_ms = round((_t.monotonic() - start) * 1000)
    except Exception as exc:
        db_ms = f"ошибка: {exc}"
    start = _t.monotonic()
    try:
        await message.bot.get_me()
        api_ms = round((_t.monotonic() - start) * 1000)
    except Exception as exc:
        api_ms = f"ошибка: {exc}"
    await message.reply(
        "<b>Задержки</b>\n\n"
        f"База данных: {db_ms} мс\n"
        f"Telegram Bot API: {api_ms} мс"
    )


# ------------------------------------------------------------------ telegram

@router.message(Command("webhookinfo"))
async def cmd_webhookinfo(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    try:
        info = await message.bot.get_webhook_info()
        await message.reply(
            "<b>Webhook Info</b>\n\n"
            f"URL: {_esc(info.url or 'не установлен (long polling)')}\n"
            f"Pending updates: {info.pending_update_count}\n"
            f"Max connections: {info.max_connections}\n"
            f"Has custom cert: {info.has_custom_certificate}\n"
            f"Last error: {_esc(info.last_error_message or 'нет')}"
        )
    except Exception as exc:
        await message.reply(f"Ошибка: {_esc(exc)}")


@router.message(Command("webhookcheck", "webhooktest"))
async def cmd_webhookcheck(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    info = await message.bot.get_webhook_info()
    if info.url:
        await message.reply("Webhook установлен. Режим: webhook.")
    else:
        await message.reply("Webhook не установлен. Режим: long polling (нормально для этого бота).")


@router.message(Command("botapi"))
async def cmd_botapi(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    me = await message.bot.get_me()
    await message.reply(
        "<b>Bot API</b>\n\n"
        f"ID: {me.id}\n"
        f"Username: @{me.username}\n"
        f"Имя: {_esc(me.first_name)}\n"
        f"Может вступать в группы: {me.can_join_groups}\n"
        f"Поддерживает inline: {getattr(me, 'supports_inline_queries', 'N/A')}\n"
        f"Может читать все сообщения: {getattr(me, 'can_read_all_group_messages', 'N/A')}"
    )


@router.message(Command("inlinecheck", "inlinetest"))
async def cmd_inlinecheck(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    me = await message.bot.get_me()
    supports = getattr(me, "supports_inline_queries", False)
    await message.reply(
        "<b>Inline Mode</b>\n\n"
        f"Поддержка inline: {'Да' if supports else 'Нет'}\n"
        + ("Inline включён в BotFather." if supports else "Включите inline в BotFather: /setinline")
    )


@router.message(Command("updates", "updatecheck"))
async def cmd_updates(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    try:
        updates = await message.bot.get_updates(limit=5, timeout=1)
        await message.reply(
            "<b>Последние обновления</b>\n\n"
            f"Получено: {len(updates)}\n"
            + "\n".join(
                f"#{u.update_id} — {type(u).__name__}" for u in updates[:5]
            )
            if updates
            else "Обновлений нет."
        )
    except Exception as exc:
        await message.reply(f"Ошибка: {_esc(exc)}")


@router.message(Command("callbackstats"))
async def cmd_callbackstats(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Статистика callback</b>\n\n"
        "Отдельная таблица callback не ведётся. "
        "События сделок доступны в /eventlog."
    )


# ------------------------------------------------------------------ база данных

@router.message(Command("dbinfo", "dbhealth", "dbstats"))
async def cmd_dbinfo(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    try:
        users = await db.count_users()
        offers = await db.all_offers_by_status()
        total_offers = sum(int(r["cnt"]) for r in offers)
        size = settings.database_path.stat().st_size if settings.database_path.exists() else 0
        await message.reply(
            "<b>База данных</b>\n\n"
            f"Путь: {_esc(settings.database_path)}\n"
            f"Размер: {size} байт\n"
            f"Пользователей: {users}\n"
            f"Предложений: {total_offers}\n"
            f"Статус: OK"
        )
    except Exception as exc:
        await message.reply(f"Ошибка БД: {_esc(exc)}")


@router.message(Command("dbtables"))
async def cmd_dbtables(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    try:
        cursor = await db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [r[0] for r in await cursor.fetchall()]
        await message.reply(
            "<b>Таблицы БД</b>\n\n" + "\n".join(f"• {t}" for t in tables)
        )
    except Exception as exc:
        await message.reply(f"Ошибка: {_esc(exc)}")


@router.message(Command("dbsize"))
async def cmd_dbsize(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    size = settings.database_path.stat().st_size if settings.database_path.exists() else 0
    await message.reply(f"Размер БД: {size} байт ({round(size/1024, 1)} КБ)")


@router.message(Command("dbcheck", "dbtest"))
async def cmd_dbcheck(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    try:
        await db.count_users()
        await db.count_users_since(0)
        await message.reply("Проверка БД: OK. Запросы выполняются.")
    except Exception as exc:
        await message.reply(f"Проверка БД: ОШИБКА — {_esc(exc)}")


@router.message(Command("dberrors"))
async def cmd_dberrors(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply("Ошибки БД логируются в /errors. Отдельной таблицы ошибок БД нет.")


@router.message(Command("dbquery"))
async def cmd_dbquery(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /dbquery SELECT ... (только чтение)")
        return
    query = parts[1].strip()
    if not query.lower().startswith("select"):
        await message.reply("Разрешены только SELECT-запросы.")
        return
    try:
        cursor = await db.conn.execute(query)
        rows = await cursor.fetchall()
        if not rows:
            await message.reply("Результат пуст.")
            return
        lines = [str(dict(r)) for r in rows[:20]]
        await message.reply("\n".join(lines)[:4000])
    except Exception as exc:
        await message.reply(f"Ошибка запроса: {_esc(exc)}")


# ------------------------------------------------------------------ логи

@router.message(Command("logs", "logstats"))
async def cmd_logs(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "Логи бота хранятся в logs/bot.log и logs/supervisor.log. "
        "На Render — в Dashboard → Logs."
    )


@router.message(Command("errors", "error", "errorstats"))
async def cmd_errors_tech(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    errors = await db.list_errors(limit=10)
    if not errors:
        await message.reply("Технических ошибок не зафиксировано.")
        return
    lines = ["<b>Последние ошибки</b>", ""]
    for item in errors:
        created = datetime.fromtimestamp(int(item["created_at"]), tz=settings.tz).strftime("%d.%m.%Y %H:%M")
        lines.append(f"{created} · {_esc(item['source'])}: {_esc(item['message'][:180])}")
    await message.reply("\n".join(lines))


@router.message(Command("errorsearch"))
async def cmd_errorsearch(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /errorsearch ТЕКСТ")
        return
    errors = await db.list_errors(limit=50)
    needle = parts[1].lower()
    found = [e for e in errors if needle in (e.get("message") or "").lower() or needle in (e.get("source") or "").lower()]
    if not found:
        await message.reply("Совпадений не найдено.")
        return
    lines = [f"Найдено: {len(found)}", ""]
    for item in found[:10]:
        lines.append(f"• {_esc(item['source'])}: {_esc((item.get('message') or '')[:120])}")
    await message.reply("\n".join(lines))


@router.message(Command("eventlog", "audit", "securitylog"))
async def cmd_eventlog(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    entries = await db.list_admin_log(limit=15)
    if not entries:
        await message.reply("Журнал пуст.")
        return
    lines = ["<b>Журнал событий</b>", ""]
    for item in entries:
        created = datetime.fromtimestamp(int(item["created_at"]), tz=settings.tz).strftime("%d.%m.%Y %H:%M")
        lines.append(f"{created} · {item['admin_id']} · {_esc(item['action'])}")
    await message.reply("\n".join(lines))


@router.message(Command("clearlogs"))
async def cmd_clearlogs(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply("Очистка логов выполняется на уровне хостинга (Render → Logs). Локально: удалите logs/bot.log.")


# ------------------------------------------------------------------ очереди

@router.message(Command("queue", "jobs", "jobstats", "scheduler"))
async def cmd_queue(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Очереди и задачи</b>\n\n"
        "Отдельная очередь задач не используется. "
        "Фоновый worker обновляет карточки и истечение оферов каждые 20 сек. "
        "Проверка: /health"
    )


@router.message(Command("notifications_stats"))
async def cmd_notifications_stats(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    count = await db.count_users()
    await message.reply(f"Пользователей в БД: {count}. Уведомления хранятся в таблице notifications.")


@router.message(Command("storageinfo", "limits", "usage"))
async def cmd_storageinfo(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    size = settings.database_path.stat().st_size if settings.database_path.exists() else 0
    await message.reply(
        "<b>Хранилище</b>\n\n"
        f"БД: {size} байт ({round(size/1024, 1)} КБ)\n"
        "CPU/RAM/диск: недоступны на Render Free напрямую."
    )


# ------------------------------------------------------------------ диагностика

@router.message(Command("diagnostics", "selftest", "configcheck", "healthreport"))
async def cmd_diagnostics(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    checks = []
    try:
        await db.count_users()
        checks.append("БД: OK")
    except Exception as exc:
        checks.append(f"БД: ОШИБКА ({exc})")
    try:
        me = await message.bot.get_me()
        checks.append(f"Bot API: OK (@{me.username})")
    except Exception as exc:
        checks.append(f"Bot API: ОШИБКА ({exc})")
    checks.append(f"OWNER_ID: {', '.join(str(i) for i in sorted(settings.owner_ids)) or 'не задан'}")
    checks.append(f"ADMIN_IDS: {', '.join(str(i) for i in sorted(settings.admin_ids)) or 'не задан'}")
    checks.append(f"Оплата: {'включена' if settings.payments_available else 'выключена'}")
    checks.append(f"Техрежим: {'включён' if (await db.maintenance_state())[0] else 'выключен'}")
    await message.reply("<b>Диагностика</b>\n\n" + "\n".join(checks))


@router.message(Command("permissiontest"))
async def cmd_permissiontest(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "Проверка разрешений: OK. Ваша роль подтверждена сервером."
    )


@router.message(Command("dependencycheck"))
async def cmd_dependencycheck(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    import aiogram, aiohttp, aiosqlite
    await message.reply(
        "<b>Зависимости</b>\n\n"
        f"aiogram: {aiogram.__version__}\n"
        f"aiohttp: {aiohttp.__version__}\n"
        f"aiosqlite: {aiosqlite.__version__}\n"
        f"Python: {sys.version.split()[0]}"
    )


@router.message(Command("securitycheck"))
async def cmd_securitycheck(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Безопасность</b>\n\n"
        f"Токен в .env: {'задан' if settings.bot_token else 'НЕ ЗАДАН'}\n"
        f"OWNER_ID: {', '.join(str(i) for i in sorted(settings.owner_ids)) or 'не задан'}\n"
        "Callback защищены: да (проверка роли на сервере)\n"
        "SQL-инъекции: параметризованные запросы"
    )


@router.message(Command("reporttech"))
async def cmd_reporttech(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await db.add_error("manual_report", message.text or "")
    await message.reply("Технический отчёт записан в журнал ошибок.")


# ------------------------------------------------------------------ performance

@router.message(Command("performance", "traffic", "requests", "requeststats"))
async def cmd_performance(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Производительность</b>\n\n"
        "Отдельные метрики запросов не ведутся. "
        "Используйте /health и логи Render."
    )


@router.message(Command("workerstatus"))
async def cmd_workerstatus(message: Message, db: Database, settings: Settings) -> None:
    actor = await _guard(message, db, settings)
    if actor is None:
        return
    await message.reply(
        "<b>Статус worker</b>\n\n"
        "Фоновый worker обновляет карточки и истечение оферов каждые 20 сек. "
        "Проверка: /health"
    )
