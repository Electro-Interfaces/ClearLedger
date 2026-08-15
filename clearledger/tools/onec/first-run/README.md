# Первый заход по новой компании

Чем **впервые** наполняется слой пространства по компании-клиенту: план счетов, проводки,
справочники, первичка, банк, НДС, учётная политика. Дальше срез **обновляется и
дополняется** наборами уровнем выше (`tools/onec/queries*`, `make-*.py`).

Работает поверх той же механики, что и обновление: `q1c.ps1` берёт данные COM-соединением
(файловая база или клиент-серверная — безразлично), `parse-first.py` разбирает дамп в JSON,
загрузчик кладёт в слой внутри backend-контейнера.

## Обязательное условие: компания уже заведена

Компания должна быть в `ECOSYSTEM_COMPANIES` стека и существовать в `companies` —
загрузчик не создаёт её сам и падает с внятным сообщением. Компания пространства это
КЛИЕНТ (одна база 1С); юрлица внутри его учёта — это `organizations`, они заводятся
первым же шагом загрузки из справочника «Организации» самой базы.

## Переменные окружения

| Переменная | Зачем | Дефолт |
|---|---|---|
| `COMPANY_SLUG` | чьи данные грузим (`promizol`, `rti`, …) | **нет**, скрипт падает |
| `LAYER_SOURCE` | пометка способа: `1c_dt` (выгрузка) или `1c_com` (живая база) | `1c_dt` |
| `AS_OF` | дата среза сальдо, `ГГГГ-ММ-ДД` | сегодня |
| `ONEC_PWD` | пароль пользователя 1С для `q1c.ps1` | пусто |

Дефолта у `COMPANY_SLUG` нет намеренно: забытая переменная подписала бы данные одной
компании другой — молча, без ошибки на экране и без следа в цифрах.

`LAYER_SOURCE` у УЖЕ загруженной компании менять нельзя: загрузчик стирает и
перезаливает только свой `source`, и записи со старой пометкой останутся рядом —
обороты удвоятся.

## Порядок

```powershell
# 1. Выгрузка (ТОЛЬКО x86 PowerShell — COM-коннектор 32-битный).
#    Файловая база:
C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass `
  -File ..\q1c.ps1 -QueryDir ..\queries-first\01-core -Base "D:\путь\к\базе" > core.out.txt
#    Клиент-серверная (пароль — через $env:ONEC_PWD, не в командной строке):
C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass `
  -File ..\q1c.ps1 -QueryDir ..\queries-first\01-core -Srvr "1c-srv:1541" -Ref "buh" -User "Читатель" > core.out.txt
```

Так по каждому набору: `02-docs`, `03-refs`, `04-refs-analytics`, `05-refs-full`,
`06-doc-lines`, `07-doc-details`, `08-people`, `09-fin`, `10-policy`, `11-bank`.

```powershell
# 2. Разбор в JSON (пары «каталог запросов : дамп»)
py parse-first.py onec-core.json   ..\queries-first\01-core:core.out.txt
py parse-first.py onec-docs.json   ..\queries-first\02-docs:docs.out.txt `
                                   ..\queries-first\03-refs:refs.out.txt `
                                   ..\queries-first\04-refs-analytics:refs2.out.txt
py parse-first.py onec-refs.json   ..\queries-first\05-refs-full:full.out.txt `
                                   ..\queries-first\06-doc-lines:lines.out.txt `
                                   ..\queries-first\07-doc-details:details.out.txt `
                                   ..\queries-first\08-people:people.out.txt
py parse-first.py onec-fin.json    ..\queries-first\09-fin:fin.out.txt
py parse-first.py onec-policy.json ..\queries-first\10-policy:policy.out.txt
py parse-first.py onec-bank.json   ..\queries-first\11-bank:bank.out.txt
```

```bash
# 3a. Доставка данных и модуля резолва юрлиц в контейнер. `resolve_org.py` в образе
#     НЕ лежит — без него загрузчики падают на импорте.
scp -o ProxyJump=ns1-jump -i ~/.ssh/mag-miran onec-*.json ../resolve_org.py root@10.10.70.53:/tmp/
ssh -J ns1-jump -i ~/.ssh/mag-miran root@10.10.70.53 "
  docker cp /tmp/resolve_org.py office-backend:/app/
  for f in /tmp/onec-*.json; do docker cp \$f office-backend:/tmp/; done"

# 3b. Загрузка. ПОРЯДОК ВАЖЕН: юрлица первыми, иначе ось организации во всём слое
#     останется пустой, а разрез по юрлицу сложит двух налогоплательщиков в одну цифру.
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-orgs.py
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-core.py
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-docs.py
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-refs.py
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-bank.py
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-fin.py
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-policy.py
COMPANY_SLUG=rti LAYER_SOURCE=1c_com exec-py.sh office load-contracts.py
COMPANY_SLUG=rti exec-py.sh office link-and-snapshot.py   # связи документов и снимок сальдо
COMPANY_SLUG=rti exec-py.sh office verify-first.py        # сверка с регистром 1С
```

`verify-first.py` сверяет загруженное с регистром бухгалтерии по годам. Не сошлось —
дальше грузить нельзя: разойдутся витрины всех приложений, которые читают слой.

## Изоляция компаний

Слой разрезан по `company_id` во всех наборах, уникальные ключи включают его же
(`uq_gl_entry_external`, `uq_accounting_doc_external`, …), запросы приложений фильтруют
по компании — вторая компания в том же пространстве не пересекается с первой. Ось
юрлица (`organization_id`) режет данные ВНУТРИ компании: у аутсорсера в одной базе
обычно ООО и ИП одного владельца.

## Грабли, проверенные прогоном

- **Организация — последней колонкой каждого запроса.** Разбор позиционный; поле в
  середине сдвинуло бы индексы сразу на всех наборах.
- **У табличной части своей организации нет** — только `Т.Ссылка.Организация`.
- **У регистра «ОтветственныеЛицаОрганизаций» юрлицо зовётся `СтруктурнаяЕдиница`**,
  реквизита `Организация` у него нет: с ним запрос падает целиком.
- **У «ДатыЗапретаИзменения» разреза по юрлицу нет вовсе** — набор `10-policy/03-locks`
  грузится без организации, это не пропуск.
- **`СчетаУчетаНоменклатуры`: поле зовётся `СчетУчета`**, не `СчетУчетаБУ`.
- Несуществующее поле роняет ВЕСЬ запрос с «Object reference not set to an instance of
  an object» — ошибка 1С маскируется под ошибку PowerShell. Имена искать `meta-find.ps1`,
  а не угадывать.

## Что этот набор не забирает

Зарплату (`queries-payroll`), книги покупок и продаж реквизитами (`queries-books`),
налоговый контур и календарь (`queries-tax`), помесячные сальдо (`queries-balances`),
связь документов с договорами отдельным срезом (`queries-contracts`), ЭДО
(`queries-edo`) — это наборы уровнем выше, они идут после первого захода.
