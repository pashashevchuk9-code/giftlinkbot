from pathlib import Path
p = Path('deals.py')
s = p.read_bytes()
idx = s.find(b'deal_text = (')
if idx >= 0:
    print("Found at:", idx)
    print(repr(s[idx:idx+300]))
else:
    print("deal_text = ( not found")