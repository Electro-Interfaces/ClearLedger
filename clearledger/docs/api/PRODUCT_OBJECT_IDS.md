# ServiceLocation IDs в product read API

Baseline `58826823c9b2e0bb77764496e153a38836e61566`, отдельная ветка
`agent/api-object-id-compat-20261030`. Это compatibility slice, не расширение
доступа или уровней модели: ServiceLocation остаётся servicePoint.

Native model хранит `ServiceLocation.id` как String(40). Общая native команда
проверяет 1..40 символов и отсутствие NUL, сохраняет Unicode и пробелы без trim,
lower или remapping. Прежний product `Id` допускает только ASCII и до128 символов.
Он использовался не только в path, но и в response DTO, включая FK links.

Отдельный `ObjectId` применяется для:

- `Object.id` и `/objects/{objectId}`;
- `/objects/{objectId}/monitoring` и `Monitoring.pointId`;
- `Equipment.objectId` и `Document.objectId`.

Остальные `Id`, UUID domains, DTO allowlists, grant/scopes, company predicates,
field-link visibility и cursor binding не меняются. Canonical auth-first resolver
сохранён: без Bearer — 401, authenticated invalid path — 422 до object/aggregate
sink. Обязательные M10/live-identity queries могут выполняться раньше; это не
обещание отсутствия auth SQL. Feature flags продолжают закрывать API независимо.

## URL и исторические значения

Строка ID передаётся в JSON и typed SET scopes без нормализации. Для path нужен
URL-encoding: Unicode/spaces и reserved `?`, `#`, `%` остаются частью ID, а не
query/fragment. 40 символов — длина Unicode строки, не UTF-8 bytes.

Native String(40) также допускает slash и control characters кроме NUL. DTO может
передавать такую историческую identity, но это не означает универсальную path
адресуемость: Starlette декодирует `%2F` в разделитель; single-segment route не
может представить любой slash ID. Dot-segments `.`/`..` могут нормализоваться
URL-клиентом до отправки. Не вводятся `:path`, новый route order или двойное
декодирование: это создало бы другую identity/маршрутизацию. Для таких значений
list/cursor остаются полезны; надёжный detail URL через произвольные proxy
не обещается. Slash также может разбить ID на сегменты другого существующего
route, например `x/monitoring`: policy этого route остаётся обязательной, но
это не detail исходного slash ID. URL controls могут отклоняться transport/proxy; локальный ASGI
roundtrip не доказывает их поддержку реальной кромкой.

## Проверка и пределы

Новый модуль `test_product_object_ids.py` включается только флагом
`RUN_PRODUCT_OBJECT_ID_TESTS=1`, pure safety guard, явным TEST_DATABASE_URL и
абсолютным test UPLOAD_DIR. Разрешённая synthetic DB — api_object_ids_test;
другие БД и runtime/VM не используются. Verifier fixture серверный fake;
результат не является OAuth/OIDC интеграцией.

Pure baseline без DB fixtures: **6 FAIL / 4 PASS**. Product отвергал native
Unicode/spaces/reserved/slash/control identities и принимал41 символ вместо
native max40. Это само по себе не доказывает HTTP500; HTTP/SQL characterization
запускается только после отдельного разрешённого SQL окна root.
Лог `.artifacts/product-object-id-pure-baseline.log`.

В выделенном root SQL окне создана только api_object_ids_test. Real HTTP baseline
на неизменённых production DTO/routes от58826823 дал **10 FAIL / 6 PASS** за19,59с:
list/cursor и видимые Equipment/Document object references возвращали500;
Unicode/spaces/reserved/control detail — 422;41 символ доходил до lookup с404.
ASCII40, прежние UUID, NUL rejection, authentication и flag-off controls работали.
Лог `.artifacts/product-object-id-http-baseline.log`.

После alias fix: **35 PASS +10 subtests** за18,97с (27 новых ID cases и8 прежних
monitoring unit/seam tests). Дополнительно прежний product HTTP/SQL набор:
**56 PASS /1 deselected** за24,82с. Исключён только заранее известный root-owned
`test_schema_and_registry_match_actual_child_routes_without_public_docs`:
в baseline588 его stale count11 не учитывает двенадцатую monitoring operation;
root ведёт это исправление отдельно, здесь тест не правился. Новый pure schema
case проверяет ObjectId/Id refs и сохранность прежнего ASCII Id pattern.

Итого91 различных PASS плюс10 subtests. Есть positive Unicode40/spaces/reserved
URL и локальный encoded newline roundtrip, lossless visible refs, 404 чужого tenant
с подменённым X-Company-Id, точный SET grant с пробелами, скрытая недоступная
object reference, no-loss/no-duplicate cursor pages и NUL/41 rejection без
ServiceLocation/charge_sessions query после identity. Auth-first401/flag-off503
сохранены; отдельного resolver wrapper нет. Логи `.artifacts/product-object-id-tests.log`
и `.artifacts/product-object-id-regression.log`.

Все pytest процессы и teardown завершены; SQL окно освобождено root к
2026-10-29 21:37:45 UTC. Other DB/VM/secrets не использованы. Полный CI, настоящий
OAuth verifier и внешние proxy/URL controls не сертифицируются этими fixtures.
