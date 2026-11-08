from pathlib import Path
p = Path("handlers.py")
s = p.read_text(encoding="utf-8")
# Change default language from "ru" to user's preference
old = '    language = "ru"\n    if len(parts) >= 2 and parts[-1].lower() in {"ua", "ru", "en", "ku"}:'
new = '    language = await db.get_user_language(inline_query.from_user.id)\n    if len(parts) >= 2 and parts[-1].lower() in {"ua", "ru", "en", "ku"}:'
assert old in s
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("done")
import ast
ast.parse(s)
print("SYNTAX OK")
