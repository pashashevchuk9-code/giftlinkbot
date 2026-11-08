from pathlib import Path
p = Path('deals.py')
lines = p.read_text(encoding='utf-8').split('\n')
if lines[905].startswith('            f"������ �{fresh[\'id\']}'):
    lines[905] = '            f"Сделка №{fresh[\'id\']}\\n"'
    lines[906] = '            f"Статус: Принято (Ожидает передачи)\\n"'
    lines[907] = '            f"NFT: {fresh[\'nft_url\']}\\n"'
    lines[908] = '            f"Покупатель: {buyer_label}\\n"'
    lines[909] = '            f"Продавец: {seller_label}\\n"'
    lines[910] = '            f"Сумма: {fresh[\'amount\']} звёзд\\n"'
    lines[911] = '            f"Осталось {remaining_hhmm}"'
    p.write_text('\n'.join(lines), encoding='utf-8')
    print('Fixed deal_text lines')
s = p.read_text(encoding='utf-8')
import ast
ast.parse(s)
print('SYNTAX OK')