#!/usr/bin/env python
"""Приёмка по канону: правила, проверяемые по исходникам.

Проверяет то, что описано в docs/WORKSPACE_UX_PATTERN_PROMPT.md — раздел
«Графики» (цвет токенами, тема подсказки, подписи дат) и правило 6.3.1
(московские сутки для колонок с зоной). Ничего не меняет: компоненты базы
генерируются во временный каталог и сравниваются с рабочими.

    python scripts/audit-canon.py          # из корня clearledger

Код возврата 1 при расхождениях — годится для запуска перед выкаткой.
Живая половина приёмки (сходимость рядов с итогами, границы суток на данных)
— в scripts/audit-live.py, она гоняется на стенде.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

OK: list[str] = []
FAIL: list[tuple[str, list[str], str]] = []


def files(root: str, ext: str):
    for dirpath, _dirs, names in os.walk(root):
        if 'node_modules' in dirpath or '__pycache__' in dirpath:
            continue
        for n in names:
            if n.endswith(ext):
                yield os.path.join(dirpath, n).replace(os.sep, '/')


def check(name: str, bad: list[str], hint: str) -> None:
    if bad:
        FAIL.append((name, bad, hint))
    else:
        OK.append(name)


def line_of(s: str, pos: int) -> int:
    return s[:pos].count('\n') + 1


# ─── Графики ───────────────────────────────────────────────────────────
bad: list[str] = []
for p in files('src', '.tsx'):
    if 'MapPanel' in p:          # карты: осознанная шкала маркеров по величине
        continue
    s = io.open(p, encoding='utf-8').read()
    for m in re.finditer(r'hsl\(\s*\d', s):
        bad.append('%s:%d' % (p, line_of(s, m.start())))
check('цвет графиков только токенами', bad,
      'литерал — цвет одной темы; на второй график разойдётся с легендой и плитками')

bad = []
for p in files('src', '.tsx'):
    if '/ui/' in p:              # компоненты базы рисуют подсказку сами
        continue
    s = io.open(p, encoding='utf-8').read()
    if 'recharts' not in s:
        continue
    for m in re.finditer(r'<Tooltip\b', s):
        blk = s[m.start():s.find('>', m.start()) + 1]
        if not any(k in blk for k in ('rechartsTooltipTheme', 'contentStyle', 'content=')):
            bad.append('%s:%d' % (p, line_of(s, m.start())))
check('подсказка ручного графика одета в тему', bad,
      'без темы recharts рисует белую плашку — на тёмной теме светится поверх данных')

bad = []
for p in files('src', '.tsx'):
    s = io.open(p, encoding='utf-8').read()
    for m in re.finditer(r'<XAxis[^>]*dataKey=["{]\s*["\']?(bucket|month|day)\b', s, re.S):
        blk = s[m.start():s.find('/>', m.start()) + 2]
        if 'tickFormatter' not in blk:
            bad.append('%s:%d' % (p, line_of(s, m.start())))
check('подписи дат на осях через formatBucket', bad,
      'сырой ISO на оси читается как код, а не как дата')

# ─── Периоды ───────────────────────────────────────────────────────────
# Колонки с зоной (данные в UTC) обязаны резаться московскими сутками.
# У ЭЗС время лежит в timestamp without time zone уже в МСК — там naive-границы
# верны, поэтому в список не входит.
TZ_AWARE = ('FuelTransaction', 'FuelShift', 'T.dt', 'FuelReceipt')
bad = []
for p in files('server/app', '.py'):
    s = io.open(p, encoding='utf-8').read()
    for m in re.finditer(r'^.*datetime\.combine\([^)]*\)|^.*datetime\(\w+\.year,[^)]*\)', s, re.M):
        line = m.group(0)
        if any(t in line for t in TZ_AWARE):
            bad.append('%s:%d %s' % (p, line_of(s, m.start()), line.strip()[:70]))
check('границы периода по колонкам с зоной — московские', bad,
      'иначе сутки сдвинуты на 3 часа: ночь последнего дня в итоге, ночь первого — нигде')

# ─── База графиков не разъехалась с генератором ────────────────────────
tmp = tempfile.mkdtemp(prefix='tremor-audit-')
try:
    env = dict(os.environ, ADAPT_DST=tmp)
    r = subprocess.run(['bash', 'scripts/adapt-tremor.sh'], env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        check('компоненты базы совпадают с генератором',
              ['scripts/adapt-tremor.sh упал: %s' % (r.stderr.strip().splitlines() or [''])[-1]],
              'без рабочего генератора обновление Tremor придётся переносить руками')
    else:
        diff = []
        for n in sorted(os.listdir(tmp)):
            cur = os.path.join('src/components/ui', n)
            if not os.path.exists(cur):
                diff.append('%s — нет в проекте' % n)
                continue
            a = io.open(os.path.join(tmp, n), encoding='utf-8').read()
            b = io.open(cur, encoding='utf-8').read()
            if a != b:
                diff.append('%s — правка мимо скрипта' % n)
        check('компоненты базы совпадают с генератором', diff,
              'правку компонента базы вносят в scripts/adapt-tremor.sh, иначе её сотрёт обновление Tremor')
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ─── Итог ──────────────────────────────────────────────────────────────
print('== СООТВЕТСТВУЕТ ==')
for name in OK:
    print('  ок   %s' % name)
if FAIL:
    print('\n== РАСХОЖДЕНИЯ ==')
    for name, bad, hint in FAIL:
        print('  !!   %s — %d шт.' % (name, len(bad)))
        print('       %s' % hint)
        for b in bad[:8]:
            print('         %s' % b)
        if len(bad) > 8:
            print('         … ещё %d' % (len(bad) - 8))
    sys.exit(1)
print('\nрасхождений нет')
