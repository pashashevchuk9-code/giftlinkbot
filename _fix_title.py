from pathlib import Path
import re
data = Path("handlers.py").read_bytes()
for m in re.finditer(rb'title=f"\?+', data):
    print(m.start(), data[m.start():m.start()+60])
# Count occurrences
count = data.count(b'title=f"?????????? {amount} Stars ?? {nft_title}"')
print("count:", count)
# Replace all
data = data.replace(b'title=f"?????????? {amount} Stars ?? {nft_title}"', b'title=f"\xd0\x9f\xd1\x80\xd0\xb5\xd0\xb4\xd0\xbb\xd0\xbe\xd0\xb6\xd0\xb8\xd1\x82\xd1\x8c {amount} Stars \xd0\xb7\xd0\xb0 {nft_title}"')
Path("handlers.py").write_bytes(data)
print("done")
# Verify
data2 = Path("handlers.py").read_bytes()
count2 = data2.count(b'title=f"\xd0\x9f\xd1\x80\xd0\xb5\xd0\xb4\xd0\xbb\xd0\xbe\xd0\xb6\xd0\xb8\xd1\x82\xd1\x8c {amount} Stars \xd0\xb7\xd0\xb0 {nft_title}"')
print("new count:", count2)
