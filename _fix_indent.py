from pathlib import Path
p = Path('deals.py')
lines = p.read_text(encoding='utf-8').split('\n')
if lines[904].startswith('                deal_text = ('):
    lines[904] = '        deal_text = ('
    print('Fixed indentation on line 905')
p.write_text('\n'.join(lines), encoding='utf-8')
s = p.read_text(encoding='utf-8')
import ast
ast.parse(s)
print('SYNTAX OK')