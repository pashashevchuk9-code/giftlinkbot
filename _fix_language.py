from pathlib import Path
p = Path("handlers.py")
s = p.read_text(encoding="utf-8")

marker = "router.include_router(menu_router)\n"
handler = '''@router.message(Command("language"))
async def cmd_language(message: Message, db: Database, settings: Settings) -> None:
    if message.from_user is None:
        return
    actor = await get_actor(db, settings, message.from_user)
    parts = (message.text or "").split(maxsplit=1)
    langs = {"ua": "Українська", "ru": "Русский", "en": "English", "ku": "中文"}
    if len(parts) < 2:
        current = await db.get_user_language(message.from_user.id)
        lines = ["Выбор языка / Language / Мова / 语言", "", f"Текущий: {langs.get(current, current)}", "", "Доступные языки:"]
        for code, name in langs.items():
            mark = " ✓" if code == current else ""
            lines.append(f"  /language {code} — {name}{mark}")
        await message.reply("\\n".join(lines))
        return
    code = parts[1].strip().lower()
    if code not in langs:
        await message.reply("Доступные языки: ua, ru, en, ku")
        return
    await db.set_user_language(message.from_user.id, code)
    names = {"ua": "Українська", "ru": "Русский", "en": "English", "ku": "中文"}
    await message.reply(f"Язык изменён на {names[code]}.")


'''
assert marker in s
s = s.replace(marker, handler + marker, 1)
p.write_text(s, encoding="utf-8")
print("done")
import ast
ast.parse(s)
print("SYNTAX OK")
