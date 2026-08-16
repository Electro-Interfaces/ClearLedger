# -*- coding: utf-8 -*-
"""Коннектор к 1С: один вход вместо тридцати ручных шагов.

Забирает срез компании из базы 1С COM-соединением, разбирает в нормализованный вид и
грузит в слой пространства. Порядок шагов и грабли живут ЗДЕСЬ, а не в голове — иначе
вторая компания загружается так же долго, как первая, и с теми же ошибками.

    py connector.py <slug> --base "D:\\temp\\npk-1c" [--user Иванов] [--stack office]
    py connector.py <slug> --srvr "1c-srv:1541" --ref buh --user Читатель
    py connector.py <slug> --base ... --only pull        # выгрузить и остановиться
    py connector.py <slug> --base ... --skip pull        # грузить уже выгруженное
    py connector.py <slug> --base ... --sets queries-tax # обновить один набор

Пароль базы — в переменной окружения ONEC_PWD, не в командной строке.

Этапы: pull (выгрузка) → parse (разбор) → push (доставка) → load (загрузка) →
finish (связи и сверка). Каждый можно запустить отдельно: выгрузка идёт на
Windows-машине с платформой 1С, загрузка — внутри backend-контейнера стека.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRST = HERE / 'first-run'
PS32 = r'C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe'


def _git_bash() -> str:
    """Именно Git Bash, а не `bash` из PATH: там первым отвечает WSL, а у него своя
    файловая система — `/c/...` в ней не существует, и каждый шаг молча падает."""
    env = os.environ.get('GIT_BASH')
    if env and Path(env).exists():
        return env
    for p in (r'D:\Program Files\Git\bin\bash.exe', r'C:\Program Files\Git\bin\bash.exe',
              r'D:\Program Files\Git\usr\bin\bash.exe', r'C:\Program Files\Git\usr\bin\bash.exe'):
        if Path(p).exists():
            return p
    return 'bash'


BASH = _git_bash()
EXEC_PY = Path(os.path.expanduser('~')) / '.claude' / 'skills' / 'elsy-deploy' / 'scripts' / 'exec-py.sh'
VM = 'root@10.10.70.53'
SSH = ['ssh', '-o', 'ConnectTimeout=20', '-J', 'ns1-jump', '-i',
       os.path.expanduser('~/.ssh/mag-miran'), VM]

# ── Что выгружаем. Порядок здесь не важен, важен состав. ───────────────────────
SETS = [
    'queries-first/01-core', 'queries-first/02-docs', 'queries-first/03-refs',
    'queries-first/04-refs-analytics', 'queries-first/05-refs-full',
    'queries-first/06-doc-lines', 'queries-first/07-doc-details', 'queries-first/08-people',
    'queries-first/09-fin', 'queries-first/10-policy', 'queries-first/11-bank',
    'queries', 'queries-docs', 'queries-contracts', 'queries-payroll', 'queries-payroll2',
    'queries-tax', 'queries-balances', 'queries-books', 'queries-wave3', 'queries-gap',
    'queries-gap2', 'queries-subconto', 'queries-policy',
]

# ── Разбор: JSON собирается из одного или нескольких наборов. ──────────────────
JSONS = {
    'onec-core': ['queries-first/01-core'],
    'onec-docs': ['queries-first/02-docs', 'queries-first/03-refs', 'queries-first/04-refs-analytics'],
    'onec-refs': ['queries-first/05-refs-full', 'queries-first/06-doc-lines',
                  'queries-first/07-doc-details', 'queries-first/08-people'],
    'onec-fin': ['queries-first/09-fin'],
    'onec-policy': ['queries-first/10-policy'],
    'onec-bank': ['queries-first/11-bank'],
    'onec-tax': ['queries-tax', 'queries-balances'],
    'onec-gap': ['queries-gap'],
    'onec-gap2': ['queries-gap2'],
    'onec-subconto': ['queries-subconto'],
    'onec-taxsys': ['queries-policy'],
}

# ── Генераторы: сначала кладём дампы под именами, которые они ждут. ────────────
# (генератор, {куда: откуда}, что получится)
GENERATORS = [
    ('parse.py', {'pull.out.txt': 'queries'}, None),
    ('make-loader.py', {}, 'load-pull.py'),
    ('make-enrich.py', {'enrich.out.txt': 'queries-docs'}, 'load-enrich.py'),
    ('make-wave2.py', {'w2.out.txt': 'queries-docs'}, 'load-wave2.py'),
    ('make-wave3.py', {'w3.out.txt': 'queries-wave3', 'w3b.out.txt': None}, 'load-wave3.py'),
    ('make-payroll.py', {'zpull.out.txt': 'queries-payroll',
                         'zfix.out.txt': 'queries-payroll2'}, 'load-payroll.py'),
]

# ── Порядок загрузки. Он и есть главное знание этого файла. ────────────────────
#
# `load-core` стирает ВСЕ документы компании, поэтому идёт первым из документных;
# `load-orgs` — раньше всех, иначе ось юрлица во всём слое останется пустой;
# связи и сверка — последними, когда все документы уже на месте.
LOAD_ORDER = [
    'load-orgs.py',       # карточки юрлиц из справочника «Организации»
    'load-core.py',       # план счетов, проводки, первичка, периоды
    'load-docs.py',       # счета, счета-фактуры, регламентные, справочники аналитики
    'load-refs.py',       # полные справочники, строки документов, статусы
    'load-bank.py',       # банковские документы
    'load-fin.py',        # учётная политика, книги НДС, остатки, счета учёта
    'load-policy.py',     # контакты, даты запрета, политика
    'load-contracts.py',  # договоры
    'load-tax.py',        # календарь, отчётность, ЕНС, помесячные сальдо
    'load-gap.py',        # УСН, кадры, НМА, уставный капитал, реквизиты первички
    'load-gap2.py',       # агентская схема, НДС, кадры компании-агента
    'load-subconto.py',   # виды субконто по счетам — карта для сведения аналитики
    'load-tax-system.py', # система налогообложения и ОБЪЕКТ УСН из настроек 1С
]
# Сгенерированные загрузчики едут отдельно: они везут данные внутри себя.
GENERATED_ORDER = ['load-pull.py', 'load-enrich.py', 'load-wave2.py',
                   'load-wave3.py', 'load-payroll.py']
# `relink` идёт ПЕРЕД связыванием проводок: у него своя карта видов, и вид, которого
# в ней нет, он снимает как ложную связь — то есть откатывает работу предыдущего шага.
# Карта в приложении дополнена, но на выкатанном образе живёт прежняя, и порядок
# «сначала сведение, потом связи» верен при обеих.
# `link-subconto` идёт ПОСЛЕ слияния дублей контрагентов: слияние переносит
# документы на главную карточку, и ссылки аналитики должны встать уже на неё.
FINISH_ORDER = ['relink.py', 'link-and-snapshot.py', 'merge-counterparties.py',
                'link-subconto.py', 'link-doc-contracts.py', 'verify-first.py',
                'analyze-layer.py']


def posix(p) -> str:
    """Windows-путь → путь для bash: `D:\\a\\b` → `/d/a/b`.

    Без этого bash получает строку с обратными слэшами, съедает их и не находит файл —
    молча, кодом 127 на каждый шаг, а прогон выглядит успешным.
    """
    s = str(p).replace('\\', '/')
    if len(s) > 1 and s[1] == ':':
        s = '/%s%s' % (s[0].lower(), s[2:])
    return s


def run(cmd, **kw):
    print('  $', ' '.join(str(c) for c in cmd[:6]), '...' if len(cmd) > 6 else '')
    r = subprocess.run(cmd, check=False, **kw)
    if r.returncode:
        print('  [!] код возврата', r.returncode)
    return r


def dumps_dir(slug: str) -> Path:
    d = HERE / 'dumps' / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def conn_args(a) -> list[str]:
    if a.conn:
        return ['-Conn', a.conn]
    if a.srvr and a.ref:
        return ['-Srvr', a.srvr, '-Ref', a.ref, '-User', a.user or '']
    if a.base:
        return ['-Base', a.base, '-User', a.user or '']
    sys.exit('нужна база: --base <путь> либо --srvr <сервер> --ref <имя базы> либо --conn')


def stage_pull(a):
    """Выгрузка наборов. Долгая: подключение к большой базе занимает до минуты."""
    out = dumps_dir(a.slug)
    todo = a.sets or SETS
    for name in todo:
        qdir = HERE / name
        if not qdir.is_dir():
            print('  пропуск, нет каталога:', name)
            continue
        target = out / (name.replace('/', '_') + '.out.txt')
        print('— выгрузка', name)
        with open(target, 'w', encoding='utf-8') as f:
            run([PS32, '-ExecutionPolicy', 'Bypass', '-File', str(HERE / 'q1c.ps1'),
                 '-QueryDir', str(qdir)] + conn_args(a), stdout=f, stderr=subprocess.STDOUT)
        bad = [l for l in open(target, encoding='utf-8', errors='replace') if 'FAILED' in l]
        for l in bad:
            print('  [!]', l.strip()[:160])


def dump_of(a, set_name: str) -> Path:
    return dumps_dir(a.slug) / (set_name.replace('/', '_') + '.out.txt')


def stage_parse(a):
    """Разбор дампов: часть — универсальным parse-first, часть — своими генераторами."""
    out = dumps_dir(a.slug)
    for target, sets in JSONS.items():
        pairs = ['%s=%s' % (HERE / s, dump_of(a, s)) for s in sets if dump_of(a, s).exists()]
        if not pairs:
            continue
        print('--', target)
        run([sys.executable, str(FIRST / 'parse-first.py'), str(out / (target + '.json'))] + pairs)

    # Генераторы читают дампы из своего каталога под фиксированными именами.
    for script, inputs, produced in GENERATORS:
        missing = False
        for fname, src in inputs.items():
            dst = HERE / fname
            if src is None:
                dst.write_text('', encoding='utf-8')   # пустой файл-заглушка
                continue
            if not dump_of(a, src).exists():
                missing = True
                break
            shutil.copyfile(dump_of(a, src), dst)
        if missing:
            print('  пропуск', script, '— нет дампа')
            continue
        print('--', script)
        run([sys.executable, str(HERE / script)], cwd=str(HERE))
        if produced and (HERE / produced).exists():
            shutil.move(str(HERE / produced), str(out / produced))
    # Временные дампы генераторов в репозитории не оставляем.
    for fname in ('pull.out.txt', 'enrich.out.txt', 'w2.out.txt', 'w3.out.txt', 'w3b.out.txt',
                  'zpull.out.txt', 'zfix.out.txt', 'pull.json'):
        (HERE / fname).unlink(missing_ok=True)


def stage_push(a):
    """Доставка данных на ВМ и внутрь контейнера.

    `resolve_org.py` в образе не лежит, а /tmp контейнера живёт до ближайшего выката —
    поэтому доставка повторяется перед каждой загрузкой, а не один раз.
    """
    out = dumps_dir(a.slug)
    files = sorted(out.glob('onec-*.json')) + sorted(out.glob('load-*.py')) + [HERE / 'resolve_org.py']
    run(['scp', '-o', 'ProxyJump=ns1-jump', '-i', os.path.expanduser('~/.ssh/mag-miran')]
        + [str(f) for f in files] + ['%s:/tmp/' % VM])
    run(SSH + ['docker cp /tmp/resolve_org.py {s}-backend:/app/ >/dev/null; '
               'for f in /tmp/onec-*.json; do docker cp $f {s}-backend:/tmp/ >/dev/null; done; '
               'echo доставлено'.format(s=a.stack)])


def exec_in_container(a, script: Path, extra_env=None):
    env = dict(os.environ)
    env['COMPANY_SLUG'] = a.slug
    env['LAYER_SOURCE'] = a.source
    env.update(extra_env or {})
    # Оба пути — в posix-виде: скрипт запускается через bash, а не через cmd.
    return run([BASH, posix(EXEC_PY), a.stack, posix(script)], env=env)


def stage_load(a):
    out = dumps_dir(a.slug)
    for name in LOAD_ORDER:
        script = FIRST / name
        if not script.exists():
            continue
        print('--', name)
        exec_in_container(a, script)
    for name in GENERATED_ORDER:
        script = out / name
        if not script.exists():
            print('  пропуск', name, '— не сгенерирован')
            continue
        print('--', name)
        # Загрузчики с данными внутри слишком велики для base64-канала exec-py.sh.
        run(['scp', '-o', 'ProxyJump=ns1-jump', '-i', os.path.expanduser('~/.ssh/mag-miran'),
             str(script), '%s:/tmp/' % VM])
        run(SSH + ['docker cp /tmp/{n} {s}-backend:/app/ >/dev/null && '
                   'docker exec -w /app -e COMPANY_SLUG={c} -e LAYER_SOURCE={src} '
                   '{s}-backend python {n}'.format(n=name, s=a.stack, c=a.slug, src=a.source)])


def stage_finish(a):
    env = {'SOURCE_NAME': a.source_name or ('1С:Бухгалтерия %s' % a.slug),
           'SOURCE_PATH': a.source_path or ('com:%s' % (a.base or a.ref or '')),}
    for name in FINISH_ORDER:
        script = FIRST / name if (FIRST / name).exists() else HERE / name
        if not script.exists():
            continue
        print('--', name)
        exec_in_container(a, script, env)


STAGES = [('pull', stage_pull), ('parse', stage_parse), ('push', stage_push),
          ('load', stage_load), ('finish', stage_finish)]


def main():
    p = argparse.ArgumentParser(description='Коннектор к 1С: срез компании в слой пространства')
    p.add_argument('slug', help='slug компании в пространстве (promizol, rti, npk)')
    p.add_argument('--base', help='путь к файловой базе 1С')
    p.add_argument('--srvr', help='сервер 1С, напр. 1c-srv:1541')
    p.add_argument('--ref', help='имя информационной базы в кластере')
    p.add_argument('--user', help='пользователь 1С (пароль — в ONEC_PWD)')
    p.add_argument('--conn', help='готовая строка соединения')
    p.add_argument('--stack', default='office', help='стек пространства (по умолчанию office)')
    p.add_argument('--source', default='1c_com', help='пометка слоя: 1c_com или 1c_dt')
    p.add_argument('--source-name', help='как назвать приём в L1')
    p.add_argument('--source-path', help='путь источника для L1')
    p.add_argument('--only', help='выполнить только этот этап')
    p.add_argument('--skip', default='', help='пропустить этапы через запятую')
    p.add_argument('--sets', nargs='*', help='выгрузить только эти наборы')
    a = p.parse_args()

    skip = {s.strip() for s in a.skip.split(',') if s.strip()}
    for name, fn in STAGES:
        if a.only and name != a.only:
            continue
        if name in skip:
            print('=== пропуск этапа', name)
            continue
        print('===', name)
        fn(a)
    print('готово:', a.slug)


if __name__ == '__main__':
    main()
