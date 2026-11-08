from pathlib import Path

# Templates with actual Unicode characters (use \\n for newlines in source)
ru_tmpl = "{buyer} предлагает Вам {stars} за подарок {nft}.\\nПредложение действует ещё {remaining}.\\n\\n{footer}"
ua_tmpl = "{buyer} пропонує Вам {stars} за подарунок {nft}.\\nПропозиція діє ще {remaining}.\\n\\n{footer}"
en_tmpl = "{buyer} offers you {stars} for gift {nft}.\\nOffer valid for {remaining}.\\n\\n{footer}"
ku_tmpl = "{buyer} 为您提供了 {stars} 的礼物 {nft}。\\n此提案有效期还有 {remaining}。\\n\\n{footer}"

new_block = (
    "    _LANG_TEMPLATES = {\n"
    '        "ru": ("' + ru_tmpl + '", "Предложение"),\n'
    '        "ua": ("' + ua_tmpl + '", "Пропозиція"),\n'
    '        "en": ("' + en_tmpl + '", "Offer"),\n'
    '        "ku": ("' + ku_tmpl + '", "提案"),\n'
    "    }\n"
)

p = Path("deals.py")
data = p.read_bytes()

start = data.find(b"    _LANG_TEMPLATES = {")
end_marker = b"    def _caption"
end = data.find(end_marker, start)
assert start != -1 and end != -1, "markers not found"

data = data[:start] + new_block.encode("utf-8") + data[end:]
p.write_bytes(data)
print("done")

s = p.read_text(encoding="utf-8")
import ast
ast.parse(s)
print("SYNTAX OK")
idx = s.find("_LANG_TEMPLATES")
print(s[idx:idx+150])
