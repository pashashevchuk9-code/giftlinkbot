from pathlib import Path
p = Path('deals.py')
lines = p.read_text(encoding='utf-8').split('\n')
# Lines 906-912 (index 905-911) contain the deal_text lines with question marks
# Replace them with proper Russian text
lines[905] = '            f"Сделка №{fresh[\'id\']}\\n"'
lines[906] = '            f"Статус: Принято (Ожидает передачи)\\n"'
lines[907] = '            f"NFT: {fresh[\'nft_url\']}\\n"'
lines[908] = '            f"Покупатель: {buyer_label}\\n"'
lines[909] = '            f"Продавец: {seller_label}\\n"'
lines[910] = '            f"Сумма: {fresh[\'amount\']} звёзд\\n"'
lines[911] = '            f"Осталось {remaining_hhmm}"'
p.write_text('\n'.join(lines), encoding='utf-8')
print('Fixed deal_text lines')
import ast
ast.parse(s)
print('SYNTAX OK')