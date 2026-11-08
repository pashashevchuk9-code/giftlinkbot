from pathlib import Path
p = Path("handlers.py")
s = p.read_text(encoding="utf-8")

# Add /id command (alias for whoami)
handler = '''
@router.message(Command("id"))
async def cmd_id(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    record = await get_actor(db, settings, message.from_user)
    await message.reply(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\\n"
        f"Роль: <b>{role_of(record).value}</b>"
    )


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    await message.reply("pong 🏓")


@router.message(Command("status"))
async def cmd_status(message: Message, db: Database, settings: Settings) -> None:
    active, until = await db.maintenance_state()
    await message.reply(
        "Статус сервиса: " + ("техрежим" if active else "работает") + "\\n"
        + ("Оплата Stars: " + ("включена" if settings.payments_available else "выключена"))
    )


@router.message(Command("notifications"))
async def cmd_notifications(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.MANAGE_NOTIFICATIONS):
        return
    enabled = await db.notifications_enabled(message.from_user.id)
    items = await db.list_notifications(message.from_user.id, limit=10)
    await db.mark_notifications_read(message.from_user.id)
    lines = ["<b>Уведомления</b>", "", f"Новые предложения: {'включены' if enabled else 'выключены'}."]
    if items:
        lines.append("")
        for item in items:
            created = __import__("datetime").datetime.fromtimestamp(int(item["created_at"])).strftime("%d.%m.%Y %H:%M")
            text = str(item["text"]).replace("\\n", " ")
            if len(text) > 160:
                text = text[:159] + "…"
            lines.append(f"{created} · {text}")
    else:
        lines.append("\\nПока уведомлений нет.")
    await message.reply("\\n".join(lines))


@router.message(Command("support"))
async def cmd_support(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_SUPPORT):
        return
    override = await db.setting_get("support_contact")
    contact = override or settings.support_contact
    if contact:
        await message.reply(f"<b>Поддержка</b>\\n\\nОбратитесь: {contact}")
    else:
        await message.reply("<b>Поддержка</b>\\n\\nКонтакт поддержки пока не указан.")


@router.message(Command("faq"))
async def cmd_faq(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_RULES):
        return
    await message.reply(
        "<b>Частые вопросы</b>\\n\\n"
        "1. Как создать предложение?\\n"
        "   В группе ответьте на сообщение продавца: @бот https://t.me/nft/Name-123 100\\n\\n"
        "2. Сколько действует предложение?\\n"
        "   48 часов.\\n\\n"
        "3. Как оплатить?\\n"
        "   После принятия продавцом вы получите счёт Telegram Stars.\\n\\n"
        "4. Как передать NFT?\\n"
        "   Автоматически (Telegram Business) или вручную.\\n\\n"
        "5. Как связаться с поддержкой?\\n"
        "   /support"
    )


@router.message(Command("mystats"))
async def cmd_mystats(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    if not await require_message_permission(message, db, settings, Permission.VIEW_PROFILE):
        return
    record = await get_actor(db, settings, message.from_user)
    completed = await db.count_completed_deals(message.from_user.id)
    await message.reply(
        "<b>Моя статистика</b>\\n\\n"
        f"ID: <code>{message.from_user.id}</code>\\n"
        f"Роль: <b>{role_of(record).value}</b>\\n"
        f"Завершённые сделки: <b>{completed}</b>"
    )


@router.message(Command("report"))
async def cmd_report(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        await message.reply("Использование: /report текст проблемы")
        return
    await db.add_error("user_report", text)
    await message.reply("Спасибо! Ваше сообщение отправлено. Мы разберёмся.")


@router.message(Command("cancel"))
async def cmd_cancel_simple(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    await message.reply("Действие отменено. Используйте /start для главного меню.")


'''
marker = "router.include_router(menu_router)\n"
assert marker in s
s = s.replace(marker, handler + marker, 1)
p.write_text(s, encoding="utf-8")
print("done")
import ast
ast.parse(s)
print("SYNTAX OK")
