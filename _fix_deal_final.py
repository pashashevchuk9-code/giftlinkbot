from pathlib import Path

p = Path("deals.py")
s = p.read_text(encoding="utf-8")

idx = s.find("deal_text = (")
if idx >= 0:
    level = 0
    end_idx = idx
    for i, ch in enumerate(s[idx:], start=idx):
        if ch == "(":
            level += 1
        elif ch == ")":
            level -= 1
            if level == 0:
                end_idx = i + 1
                break

    old_block = s[idx:end_idx]
    print("Old block found, length:", len(old_block))

    new_block = '''        deal_text = (
            f"Сделка №{fresh['id']}\\n"
            f"Статус: Принято (Ожидает передачи)\\n"
            f"NFT: {fresh['nft_url']}\\n"
            f"Покупатель: {buyer_label}\\n"
            f"Продавец: {seller_label}\\n"
            f"Сумма: {fresh['amount']} звёзд\\n"
            f"Осталось {remaining_hhmm}"
        )'''

    s = s[:idx] + new_block + s[end_idx:]
    p.write_text(s, encoding="utf-8")
    print("Replaced deal_text block")

    import ast
    ast.parse(s)
    print("SYNTAX OK")
else:
    print("deal_text = ( not found")
