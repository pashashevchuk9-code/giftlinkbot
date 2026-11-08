from pathlib import Path

p = Path("deals.py")
data = p.read_bytes()

# Find _LANG_TEMPLATES block
start = data.find(b"    _LANG_TEMPLATES = {")
end = data.find(b"    }\n", start) + len(b"    }\n")

# Build correct templates using Unicode
ru_tmpl = "{buyer} \u043f\u0440\u0435\xd0\xb4\xd0\xbb\xd0\xb0\xd0\xb3\xd0\xb0\xd0\xb5\xd1\x82 \u0412\u0430\xd0\xbc {stars} \u0437\xd0\xb0 \xd0\xbf\xd0\xbe\xd0\xb4\xd0\xb0\xd1\x80\xd0\xbe\xd0\xba {nft}.\\n\xd0\x9f\xd1\x80\xd0\xb5\xd0\xb4\xd0\xbb\xd0\xbe\xd0\xb6\xd0\xb5\xd0\xbd\xd0\xb8\xd0\xb5 \xd0\xb4\xd0\xb5\xd0\xb9\xd1\x81\xd1\x82\xd0\xb2\xd1\x83\xd0\xb5\xd1\x82 \xd0\xb5\xd1\x89\xd1\x91 {remaining}.\\n\\n{footer}"
ua_tmpl = "{buyer} \u043f\xd1\x80\xd0\xbe\xd0\xbf\xd0\xbe\xd0\xbd\xd1\x83\xd1\x94 \u0412\u0430\xd0\xbc {stars} \xd0\xb7\xd0\xb0 \xd0\xbf\xd0\xbe\xd0\xb4\xd0\xb0\xd1\x80\xd1\x83\xd0\xbd\xd0\xbe\xd0\xba {nft}.\\n\xd0\x9f\xd1\x80\xd0\xbe\xd0\xbf\xd0\xbe\xd0\xb7\xd0\xb8\xd1\x86\xd1\x96\xd1\x8f \xd0\xb4\xd1\x96\xd1\x94 \xd1\x94\xd1\x89\xd0\xb5 {remaining}.\\n\\n{footer}"
en_tmpl = "{buyer} offers you {stars} for gift {nft}.\\nOffer valid for {remaining}.\\n\\n{footer}"

new_block = (
    "    _LANG_TEMPLATES = {\n"
    '        "ru": ("' + ru_tmpl + '", "\u041f\xd1\x80\xd0\xb5\xd0\xb4\xd0\xbb\xd0\xbe\xd0\xb6\xd0\xb5\xd0\xbd\xd0\xb8\xd0\xb5"),\n'
    '        "ua": ("' + ua_tmpl + '", "\u041f\xd1\x80\xd0\xbe\xd0\xbf\xd0\xbe\xd0\xb7\xd0\xb8\xd1\x86\xd1\x96\xd1\x8f"),\n'
    '        "en": ("' + en_tmpl + '", "Offer"),\n'
    '        "ku": ("{buyer} \u4e3a\u60a8\u63d0\u4f9b {stars} \u7684\u793c\u7269 {nft}.\n\u6b64\u63d0\u6848\u6709\u6548 {remaining}.\n\n{footer}", "\u63d0\u6848"),\n'
    "    }\n"
)

data = data[:start] + new_block.encode("utf-8") + data[end:]
p.write_bytes(data)
print("done")

# Verify
s = p.read_text(encoding="utf-8")
idx = s.find("_LANG_TEMPLATES")
print(repr(s[idx:idx+200]))
import ast
ast.parse(s)
print("SYNTAX OK")
