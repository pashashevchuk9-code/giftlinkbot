from pathlib import Path

# Use unicode code points to avoid encoding issues
text = (
    "\u0421\u0434\u0435\u043b\u043a\u0430 \u0431\u044b\u043b\u0430 "
    "\u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u043e "
    "\u043f\u0440\u0438\u043d\u044f\u0442\u0430. "
    "\u0421\u043a\u0438\u043d\u044c\u0442\u0435 NFT "
    "\u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u043c\u0443 "
    "\u0433\u0430\u0440\u0430\u043d\u0442\u0443 @GiftIinkGaurantBot"
)

p = Path("deals.py")
data = p.read_bytes()
lines = data.split(b"\n")

# Find the line with callback.answer and show_alert
for i, line in enumerate(lines):
    if b"callback.answer" in line and b"show_alert=True" in line:
        new_line = ('            await callback.answer("' + text + '", show_alert=True)').encode("utf-8")
        lines[i] = new_line + b"\r"
        print("updated line", i + 1)
        break

p.write_bytes(b"\n".join(lines))
print("done")

import ast
ast.parse(p.read_text(encoding="utf-8"))
print("SYNTAX OK")

# Verify
data2 = p.read_bytes()
lines2 = data2.split(b"\n")
decoded = lines2[885].decode("utf-8")
print("has Сделка:", "Сделка" in decoded)
print("has гаранту:", "гаранту" in decoded)
