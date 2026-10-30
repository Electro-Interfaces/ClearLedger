# Source-only review immutable canonicalizer, 30.10.2026

Четыре заявленных cast-шаблона сохраняют значения, порядок и внешний SQL при
предпосылках из предыдущего semantic review. Статически найдено одно
отклонение от обещанного conservative scope: неподдержанный вложенный ARRAY
не остаётся целиком raw, поскольку обход нормализует его внутренний ARRAY.
Семантически ложная эквивалентность в четырёх разрешённых формах не доказана;
безусловный PASS всей заявленной границе и будущему actual-run не выдан.

## Закреплённый вход и метод

Рассмотрена только immutable копия `run_schema_restore_proof.py` из
`schema-restore-canonicalizer-review-20261030`, SHA256
`c79acf3def7a75302ad89922ce87882e4bf4f94fef018d83d653f639c4ecdc79`.
Хеш вычислен до чтения исходника; соседний snapshot.json подтверждает его и
называет scope pure tokenizer/array/canonical row/tests плюс future readonly
cast controls. База ветки — `d3ee0bf96522c79cd04db7c2656a0799df6bc3c1`.

Использованы чтение исходника с номерами строк, stdlib AST/call-site анализ и
`compile(AST, ..., 'exec')` **без exec**. Candidate, pure functions, controls,
приложение, драйверы, pytest, SQL и контейнеры не запускались. Moving WIP не
читался. Номера строк ниже относятся только к этому SHA.

Supporting input: ранее закреплённые четыре attempt4 файла и их exact hashes
приведены в [semantic review](SCHEMA_RESTORE_CAST_REVIEW_20261030.md).
Его вывод о 50 парах не повторяется как новый прогон реализации.
Сообщённые автором результаты 4 positive / 22 negative / 14 raw unknown /
2514 catalog rows / 50 pairs, PASS за 0.203492739 s — **авторский receipt из
dispatch, не независимо повторённое измерение**. Сам receipt файл в этом
review не проверялся.

## R1: обход нормализует неподдержанный nested ARRAY

**P2 для приёмки conservative scope; не доказанный дефект данных.**
`canonical_sql`, строки 190–203: если `array_fragment` возвращает None,
index увеличивается на один и поиск продолжается внутри отвергнутой формы.
Нет контекстного запрета на ARRAY, вложенный в другой ARRAY.

Синтетический контрпример, выведенный по исходнику без исполнения:

```sql
ARRAY[ARRAY['a'::character varying]::text[]]
ARRAY[ARRAY['a'::character varying::text]]
```

Ожидание заявленного nested raw/refuse scope: каждый вход остаётся своим
`[('raw', original_sql)]`, результаты различаются.
Статически прослеживаемое поведение: внешний ARRAY отвергается в строках
138–144, затем внутренний распознаётся; оба результата равны:

```text
[('raw','ARRAY['),
 ('unbounded_varchar_to_text_array', (('literal', "'a'"),)),
 ('raw',']')]
```

Само это равенство семантически корректно при оговорённых cast-условиях:
меняется только представление внутреннего массива. Finding состоит в
необъявленном расширении domain принятия, а не в доказательстве false
equivalence или false rejection. Наблюдаемые 50 пар этим примером не затронуты.
Нужны решение ROOT о границе и соответствующий negative control либо явно
согласованный более широкий compositional scope; код здесь не менялся.

## Проверенные границы реализации

| Участок | Вывод из исходника |
|---|---|
| `sql_tokens`, 72–115 | Quotes непрозрачны; doubled quotes поглощаются внутри токена. Comments и `$` вне quotes дают целиком raw. E/U&/bit/N prefixes перед строкой отвергаются. Незакрытые quotes и несбалансированные круглые/квадратные скобки дают raw. |
| `array_fragment`, 118–181 | Полностью потребляет только распознаваемый span: все элементы plain literal либо точный NULL, затем `::character varying`; стиль элементов однородный. Typmod, qualifier, COLLATE внутри span и иные типы не проходят grammar. |
| Exact templates, 164–178 | Допускаются source cast на ARRAY, с одной группировкой операнда или без неё, и target cast на каждом элементе, с одной группировкой varchar-операнда или без неё. Смешанные стили, parenthesized source elements и grouped distributed outer ARRAY отвергаются. Исходная подстрока должна точно равняться восстановленному шаблону. |
| `canonical_sql`, 184–206 | Raw prefix/suffix и внешняя группировка сохраняются точными подстроками. Только cast-span становится tagged tuple; список raw частей не сериализуется обратно в SQL. Есть исключение R1 для поиска внутри неизвестных составных форм. |
| Typed nodes, 139–155, 179 | Literal хранит весь исходный quoted token; NULL имеет отдельный tag. Порядок, число, case и пробелы внутри литералов не меняются. Raw строка с текстом маркера не становится структурным узлом. |
| `logical_catalog_row`, 209–216 | Копируется вся запись. Меняется только cell 7 для constraints типа `c`, либо cell 3 для indexes. Все имена, флаги и прочие cells сохраняются; остальные категории не трансформируются. |

Полное потребление относится к распознанному span, а не ко всему SQL:
например, внешний cast/COLLATE остаётся raw suffix, поэтому его изменение не
исчезает при сравнении. Lexer не является PostgreSQL parser: он проверяет
баланс скобок, но не валидность всей внешней грамматики. Граница trusted
pg_get_*def остаётся существенной. ASCII-word scanning не служит полной
проверкой PostgreSQL identifier boundaries для произвольного пользовательского
SQL; доказательства false equivalence на валидном deparser-выводе не получено.

Adjacent plain strings внутри ARRAY статически отвергаются: после первого
literal ожидается `::`, следующий literal не совпадает с ним. Quoted identifiers
не совпадают по raw token с ARRAY/типами; квалифицированный ARRAY после точки
исключён в строке 193. NULL, doubled quotes и backslash не встречались в
наблюдаемых 205 элементах: первые два дополнительно охвачены авторскими
positive templates, а backslash безопасен только при проверенном
`standard_conforming_strings=on`. Независимого исполнения этих расширений нет.

## Pure controls и сохранность evidence

Строки 223–259 строят четыре positive forms на одном ordered наборе из case,
пробела, NULL и doubled-quote литерала. Negative count 22 складывается из
14 SQL mutations, одного marker-collision control и семи изменений flags.
14 unknown cases проверяют raw результат, включая E/U&, comments, qualifiers,
typmod, неверный case типа, незакрытую строку/скобку и нестандартное
внутреннее форматирование. Эти количества следуют из AST/циклов, не из запуска.

Строки 268–286 pin два corpus SHA256, проверяют равенство ключей и полных
logical rows, затем требуют 50 изменённых пар и 2514 строк. Lookup по именам
не подменяет нормализацию: ключи служат только pairing, само принятие
определяет общий parser. Dictionary comprehension не проверяет дубликаты
самостоятельно; для этих exact pinned catalogs их отсутствие ранее
независимо подтверждено, поэтому здесь это не потеря наблюдаемых записей.

Оставшиеся пробелы controls: нет nested R1, adjacent-string control, mixed
styles, backslash, mutation числа/дубликатов элементов, quoted identifier
mutation в окружающем SQL, либо отдельной матрицы `<> ALL` и compound
предикатов. На последних контекстах есть observed full-row equality, но нет
независимых mutation controls. `pure_canonical_controls` в этом файле только
определена: main/run её не вызывает; её receipt остаётся отдельным авторским
шагом, а не автоматически выполненным guard будущего actual-run.

`snapshot`, строки 583–615, сохраняет отдельно exact raw canonical rows и
raw hashes; logical hashes считаются через `logical_catalog_row` для всех
категорий с counts. Data/sequence state не нормализуются этим parser.
`comparison_diagnostics`, 313–335, отдельно показывает различия raw hashes и
logical/data/totals. Проверка `before == after` в строке 721 использует logical
catalog, а raw различия остаются evidence, не стираются. Ignorekeys,
allowlist по именам объектов или потери metadata fields в этой цепочке нет.
Это сознательная смена отношения сравнения, не ретроактивный PASS attempt4.
В pure helper call graph нет app/driver imports, SQL или metadata writes;
весь surrounding restore harness этим утверждением не сертифицируется.

## Future native controls: что есть и чего ещё нет

`native_cast_controls`, 487–513, содержит readonly repeatable-read транзакцию
и проверяет pg_cast 1043→25, method `b`, context `i`, плюс
`standard_conforming_strings=on`. Предусмотрены равенства четырёх пар массивов
с NULL/duplicates, order-negative и шесть ожидаемых truth values для
`= ANY`/`= ALL`. AST показывает только SELECT внутри этого helper;
его SQL не выполнялся и ожидаемые results здесь не измерены.

В run имеется **один** вызов helper — строка 648, на SOURCE до bootstrap.
На TARGET и после restore/последующих connect (715–719) повторной проверки
нет. Same cluster (646) не является самостоятельным доказательством
одинаковых database/session defaults. Если ROOT полагается на native guard
для canonicalization обеих сторон, этот пробел должен быть закрыт или
компенсирован отдельным закреплённым доказательством условий обеих сторон.

Прочие непокрытые требования предыдущего review: фактические pg_type
namespace/type identity, castfunc 0, разрешение/strictness операторов,
effective collation и её свойства. `connect`, 443–446, задаёт pg_catalog
search_path, что ограничивает resolution; это не проверка всей metadata.
Матрица не содержит наблюдаемый **`<> ALL`**, NULL array, empty array,
CHECK acceptance, membership/уникальность partial indexes или исходные
AND/OR guards. Равенство типизированных массивов даёт основание для
семантического вывода, но не превращает эти отсутствующие controls в
проверенные измерения. Новые source-only предпосылки не выдаются за actual bug.

Итог для ROOT: conditional core-four-form review при built-in cast/type и
literal settings положителен, conservative nested scope требует решения R1;
actual SQL matrix/preconditions требуют отдельного review и разрешённого
root-run. Реализация не исполнялась, past strict restore FAIL остаётся FAIL,
full restore acceptance и разрешение release данным документом не выдаются.
