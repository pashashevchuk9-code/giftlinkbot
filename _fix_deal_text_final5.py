from pathlib import Path

p = Path("deals.py")
data = p.read_bytes()

# Find the deal_text block using bytes
old_block = b'''        deal_text = (
            f"\xd4\x21\xd0\xb5\xd0\xbb\xd0\xb3\xd0\xb0\xd0\xb5\xd1\x82 \u0001{fresh[\'id\']}\\n"\n            f"\xd4\x21\xd0\xb7\u0441\u0442\u0430\u0442\u0443\u0441: \u041f\u0440\u0438\u043d\u044f\u0442\u043e (\u041e\u0436\u0438\u0434\u0430\u0435\u0442 \u043f\u0435\u0440\u0435\u0434\u0430\u0447\u0438)\\n"
            f"NFT: {fresh[\'nft_url\']}\\n"
            f"\xd4\x1f\xd0\xbe\xd0\xba\u0443\u043f\u0430\u0442\u0435\u043b\u044c: {buyer_label}\\n"
            f"\xd4\x1f\xd0\xbe\xd0\xba\u0446\u0430\u043b\u0435\u0440: {seller_label}\\n"
            f"\xd4\x21\xd0\xb2\u043e\u043f: {fresh[\'amount\']} \u0417\u0432\u0435\u0437\u0434\\n"
            f"\xd4\x1f\xd0\xbe\u0441\u0442\u0430\u043b\u043e\u0441\u044c {remaining_hhmm}"
        )'''

# Actually, let's just do a simpler approach - find and replace the specific lines
new_block = '''        deal_text = (
            f"Сделка №{fresh['id']}\\n"
            f"Статус: Принято (Ожидает передачи)\\n"
            f"NFT: {fresh['nft_url']}\\n"
            f"Покупатель: {buyer_label}\\n"
            f"Продавец: {seller_label}\\n"
            f"Сумма: {fresh['amount']} звёзд\\n"
            f"Осталось {remaining_hhmm}"
        )'''

# Find the deal_text block
idx = s.find(b'deal_text = (')
if idx == -1:
    print("deal_text = ( not found")
else:
    # Find the closing paren
    level = 0
    end_idx = idx
    for i, ch in enumerate(s[idx:], start=idx):
        if ch == ord('('):
            level += 1
        elif ch == ord(')'):
            level -= 1
            if level == 0:
                end_idx = i + 1
                break
    
    print(f"Found block from {idx} to {end_idx}, length {end_idx - idx}")
    print("Old block:", s[idx:end_idx][:200])
    
    s = s[:idx] + new_block.encode('utf-8') + s[end_idx:]
    p.write_bytes(s)
    print("Replaced deal_text block")
    
    import ast
    ast.parse(s)
    print("SYNTAX OK")