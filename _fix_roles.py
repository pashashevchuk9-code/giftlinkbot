from pathlib import Path
p = Path("roles.py")
s = p.read_text(encoding="utf-8")
old = """TECH_COMMANDS: list[tuple[str, str]] = [
    ("/userinfo", "информация о пользователе"),
    ("/ban", "заблокировать пользователя"),
    ("/unban", "разблокировать пользователя"),
    ("/warnings", "предупреждения пользователя"),
    ("/warn", "выдать предупреждение или временное ограничение"),
    ("/untimeout", "снять временное ограничение"),
    ("/active", "активные сделки"),
    ("/errors", "технические ошибки"),
]"""
new = """TECH_COMMANDS: list[tuple[str, str]] = [
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
]"""
assert old in s, "TECH_COMMANDS not found"
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("done")
import ast
ast.parse(s)
print("SYNTAX OK")
