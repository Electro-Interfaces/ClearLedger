# Contract create body: SOURCE freeze 01.11.2026

**SOURCE-only / runtime0. Тесты AUTHORED NOTRUN.** Base `aaf472b8123bf1d01538049ef8b5308c9b72fd6b`.

Это самостоятельная реализация bounded body и нового hash-v1 для будущего POST /api/v1/contracts. Endpoint не зарегистрирован. Старые read DTO, policy, identity, Query, schema и SDK не меняются. Последующие schema/H01 handoff имеют приоритет над старыми proposals: здесь нет лимита истории receipts, materialization UUID или новой authority.

## Публичный Source contract

- `ContractCreateBody` и `ContractCreateLocations`: Pydantic strict/frozen/extra=forbid, прямые wire camelCase без alias, вложенные locationIds становятся tuple только после проверки exact raw list.
- `async parse_contract_create_body(request: starlette.requests.Request) -> ContractCreateBody`: request.stream(), реальный лимит 16384 bytes включительно; Content-Length не используется, oversized chunk не копируется и следующие chunks не читаются.
- `ContractCreateBodyError`: безопасные `status`/`code` 413/request_too_large, 415/unsupported_media_type, 422/invalid_request. Текст фиксирован; raw input/context/cause не сохраняются в parser/hash boundary error. Прямой Pydantic model_validate может выдавать ValidationError; transport использует безопасную функцию.
- `canonical_contract_create_bytes(body) -> bytes` и `contract_create_hash(body) -> str`: только exact Body instance, затем fresh validation raw fields; dict/dataclass/subclass, invalid model_construct/model_copy payload не хэшируются. Проверяются точные ключи root/nested и bounded tuple до list copy.
- Модуль импортирует только stdlib, Pydantic и Starlette Request; нет app/DTO/config/settings/ORM/identity/SQL/claims. Для isolated tests файл загружается напрямую через importlib, без существующего product_api/__init__, который импортирует app.

Wire: kind=contract-card; creationKey/organizationId/counterpartyId exact hyphenated ASCII UUID string, uppercase разрешён; explicit typed validation также принимает exact UUID. bool/int/bytes/subclasses запрещены. date хранится exact YYYY-MM-DD после calendar validation, date/datetime/timestamp coercion нет. number/type exact nonblank 1..100; typeCode exact nonblank 1..256 без enum. validUntil required nullable exact string 0..20, без date inference; null и empty различны. comment optional nullable exact string ≤2000, omission=null. Все строки UTF8-encodable/PostgreSQL text: NUL и lone surrogate запрещены. Coverage только locations; 1..100 уникальных exact native ObjectId длиной 1..40 Unicode scalar values. Пробелы/регистр/Unicode normalization/URI-looking IDs сохраняются.

Media: ровно один Content-Type application/json с optional token charset=utf-8; media/charset case-insensitive, OWS разрешён. Quoted charset, другие параметры, comma lists и duplicate headers запрещены. Content-Encoding отсутствует либо один identity (case-insensitive/OWS); duplicate encoding также запрещён. Другие encodings дают415, decompression отсутствует. Strict UTF8 JSON object only; duplicates на любой глубине, nonfinite constants, trailing documents, BOM, malformed/deep JSON дают422. Upstream stream exceptions, cancellation и disconnect не превращаются в body error.

Transport byte cap применяется к реальному stream. Typed/canonical validation проверяет поля и их границы, но не восстанавливает размер исходной wire-сериализации с её escape/whitespace. Caller выполняет свою admission/auth/quota до подключения parser и далее владеет transaction/response.

## Hash-v1

SHA256 от UTF8 JSON с ensure_ascii=False, sort_keys=True, separators=(",", ":"). Payload содержит version=1 и kind/number/date/type/typeCode/organizationId/counterpartyId/coverage/validUntil/comment. creationKey исключён: это отдельный idempotency namespace. Actor/company/app/install/grant/credential/token/jti не входят и не принимаются из body. UUID lower-hyphenated; date exact ISO; locationIds сортируются по exact Unicode scalar sequence, без normalization. Остальные строки exact.

Golden bytes ниже заданы буквальным JSON, без завершающего newline; JSON companion дополнительно хранит полный UTF8 hex. Golden digest вычислен stdlib от literal, не выполнением implementation helper.

### base: 343 bytes

```json
{"comment":null,"counterpartyId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","coverage":{"kind":"locations","locationIds":["A ","é","é","я","￿","😀"]},"date":"2024-02-29","kind":"contract-card","number":" Д-01 ","organizationId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","type":" Lease ","typeCode":"Custom/А ","validUntil":null,"version":1}
```

SHA256 `d11891751cc46939e67c4f41312af59d85dbe4b48a477bb7369ba3def36df3d8`.

### valid_until_empty: 341 bytes

```json
{"comment":null,"counterpartyId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","coverage":{"kind":"locations","locationIds":["A ","é","é","я","￿","😀"]},"date":"2024-02-29","kind":"contract-card","number":" Д-01 ","organizationId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","type":" Lease ","typeCode":"Custom/А ","validUntil":"","version":1}
```

SHA256 `ca612fc837888c422a0fad83280dc811cfe0da42f123f2f003308109f22cc77e`.

### number_whitespace: 341 bytes

```json
{"comment":null,"counterpartyId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","coverage":{"kind":"locations","locationIds":["A ","é","é","я","￿","😀"]},"date":"2024-02-29","kind":"contract-card","number":"Д-01","organizationId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","type":" Lease ","typeCode":"Custom/А ","validUntil":null,"version":1}
```

SHA256 `74b66c5002c9710fd1612920851aa1e67d0a9c0eba1df7c3caabc8acebc83b60`.

### type_case: 343 bytes

```json
{"comment":null,"counterpartyId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","coverage":{"kind":"locations","locationIds":["A ","é","é","я","￿","😀"]},"date":"2024-02-29","kind":"contract-card","number":" Д-01 ","organizationId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","type":" lease ","typeCode":"Custom/А ","validUntil":null,"version":1}
```

SHA256 `233cbbf4fcf2184cb762010cf544082bb326b25210afe2a34d9047ee77a49579`.

Эквивалентные варианты base: порядок wire members/locationIds и uppercase/lowercase UUID, другой creationKey, comment omitted/null. Различные варианты: validUntil null/empty, comment null/empty, exact whitespace/case number/type/typeCode. U+00E9 и U+0065 U+0301 остаются разными IDs; U+FFFF сортируется перед U+1F600.

## Authored inventory

27 методов unittest/IsolatedAsyncioTestCase. Параметры ниже описывают написанные случаи; это не runtime collection/results и не замена 144 proposed integration cases.

- `ContractCreateModelTests.test_valid_exact_frozen_models`: exact model classes; tuple storage; preserved text/default; frozen root/nested and tuple assignment.
- `ContractCreateModelTests.test_all_required_fields`: each of 10 required root fields; both required coverage fields.
- `ContractCreateModelTests.test_forbidden_fields_every_level_and_snake_aliases`: 25 forbidden names at root and coverage (50 combinations); 5 camelCase-to-snake replacements.
- `ContractCreateModelTests.test_discriminators_and_coverage_shape`: 5 root kind/coverage shape cases; 8 coverage discriminator values.
- `ContractCreateModelTests.test_uuid_strict_wire_and_exact_typed_uuid`: 3 UUID fields x 16 invalid and 3 valid forms (lowercase/uppercase/exact UUID).
- `ContractCreateModelTests.test_strict_calendar_date`: 22 invalid dates/types and 3 valid boundary/leap dates.
- `ContractCreateModelTests.test_text_bounds_types_and_nonblank`: 5 text fields x 3 valid values; 8 invalid types/lengths each plus 5 nonblank violations for 3 fields.
- `ContractCreateModelTests.test_postgres_text_and_utf8_every_text_field`: 5 text fields x 3 invalid NUL/surrogate strings; 3 invalid location strings.
- `ContractCreateModelTests.test_location_bounds_raw_arrays_and_element_types`: 19 invalid raw arrays/elements including list subclass; 3 valid arrays (1/100/space ID).
- `ContractCreateModelTests.test_location_uniqueness_uses_exact_unicode_identity`: 10 distinct Unicode/space/case/URI-looking identifiers; 4 exact duplicate pairs.
- `ContractCreateModelTests.test_required_nullable_and_optional_nullable_distinctions`: required validUntil null/missing/empty/non-date; comment omitted/null/empty.
- `ContractCreateModelTests.test_canonical_independent_literal_and_digest`: independent 343-byte literal plus fixed SHA256 (no encoder oracle).
- `ContractCreateModelTests.test_canonical_order_uuid_spelling_comment_and_creation_key`: reversed locations/member order; lower UUID spelling; different creationKey; comment omitted=null.
- `ContractCreateModelTests.test_canonical_exact_differences`: 3 fixed bytes/digest variations (empty validUntil, number whitespace, type case); 2 additional exact differences.
- `ContractCreateModelTests.test_canonical_rejects_non_exact_model`: 5 non-exact inputs (dict/None/object/dataclass/model subclass) x 2 helpers.
- `ContractCreateModelTests.test_canonical_revalidates_model_construct_and_copy`: 26 corrupt construct/copy instances x 2 helpers; 1 valid constructed instance revalidated.
- `ContractCreateParserTests.test_real_request_chunked_utf8_and_no_body_method`: 4 chunk stream including empty chunk; forbidden body(); bytewise stream splitting UTF8 scalars.
- `ContractCreateParserTests.test_content_length_missing_false_zero_large_and_invalid`: 6 Content-Length variants: missing/0/1/huge/invalid/negative.
- `ContractCreateParserTests.test_inclusive_actual_byte_boundary`: actual bytes 16383/16384 accepted, 16385 rejected; Unicode payload.
- `ContractCreateParserTests.test_oversized_chunk_stops_before_more_receive_and_before_json`: oversized first chunk and cumulative excess second chunk; trailing chunk remains unread; 413 before malformed JSON.
- `ContractCreateParserTests.test_media_accepts_only_json_optional_utf8_token`: 4 media tokens x 3 encodings: absent/identity/mixed-case identity.
- `ContractCreateParserTests.test_media_rejections_do_not_read_stream`: 22 rejected header combinations: absent/duplicate type, 13 bad media values, 6 bad encodings, duplicate encoding; zero reads.
- `ContractCreateParserTests.test_json_objects_only_malformed_trailing_and_constants`: 21 malformed/non-object/trailing/nonfinite inputs plus 3 nonfinite validUntil replacements.
- `ContractCreateParserTests.test_duplicate_keys_at_root_nested_and_escaped_spelling`: 6 duplicates: root, validUntil, coverage kind, nested object, nested array object, escaped-equivalent key.
- `ContractCreateParserTests.test_invalid_utf8_escaped_surrogates_nul_and_deep_json`: 8 invalid UTF8/surrogate/NUL/deep inputs; 1 valid escaped surrogate-pair scalar.
- `ContractCreateParserTests.test_parser_maps_dto_failure_without_raw_input`: unknown authority field and oversized DTO string; safe status/code, no raw value/context/cause.
- `ContractCreateParserTests.test_cancellation_disconnect_and_upstream_errors_propagate`: same-object CancelledError/RuntimeError propagation after one chunk; ASGI disconnect => ClientDisconnect.

## Source pins и проверка

- `clearledger/server/app/product_api/contract_create_body.py`: SHA256 `07c5b7976bc6284a6dc10b43579aaa41047c41e8581d34a19f5f93338b824a8e`.
- `clearledger/server/tests/test_partner_contract_create_body.py`: SHA256 `4cb2c54213d736e057e4415f12b226646be8c8a171b07c3f227341a8364aba5e`.

Выполнены только filesystem/Git и stdlib AST/JSON/hash/in-memory compile без exec. Код модулей, Pydantic, Starlette, parser/hash и тесты не импортировались/не выполнялись. Нет pytest/collection, SQL/SSH/Docker/Node/compiler/browser/install/network/PoC. JSON companion фиксирует входные source pins и inventory; SHA самого MD/JSON передаётся вместе с exact local commit, без циклических self hashes.

Runtime0 не доказывает работоспособность Pydantic discriminator/validators или ASGI поведения: Root отдельно делает hermetic isolated execution actual models/Request. Нет auth/quotas/DB/HTTP registration/response DTO/SDK/runtime proof. Полный M00–M19+11, включая real144 и дальнейшее подключение обоих principals, остаётся открыт. Публикация/push/PR/merge/deploy не выполнены; local commit [skip ci] передаётся Root для Source review.
