# Переносимость type_code в тесте карточки договора

Узкий follow-up к frozen PR95, exact parent `2e1a96d5fbee291c93e2b3869028af01d6c40a57`; ROOT `msg_684881805510`. Новый HEAD — exact3-path коммит с этими отчётами, его точный OID передаётся внешним sourcefreeze status. Собственный commit/hash внутри отчёта не замыкается на себя.

В narrow metadata колонка Contract.type_code объявлена без ORM FK (`server/app/models.py:1405–1410`). Full-profile DDL содержит `type_code TEXT REFERENCES contract_types(code)` (`server/app/database.py:3610`). Наличие installed `contracts_type_code_fkey` сообщено ROOT и независимым crossreview; runtime здесь UNKNOWN/NOTRUN. `ADD COLUMN IF NOT EXISTS` не доказывает наличие FK в конкретной БД и не чинит ранее созданную колонку.

Empty-strings case больше не требует успешного сохранения отсутствующего catalog code "": он сохраняет `card_values(w).type_code == w.active` (`server/tests/test_contract_card_creation.py:43–57`), реальный fixture code задаётся в native world (`server/tests/test_native_contract_create.py:105–109`). Native `_check_type_code` для пустого кода возвращает None (`server/app/services/reference_validation.py:36–44`, вызов `server/app/services/native_contract_commands.py:62`). Production regression не заявляется.

Единственная test-правка, строки146 и150:

```diff
-        values = replace(values, number="", date="", type="", type_code="", kind="", currency="",
+        values = replace(values, number="", date="", type="", kind="", currency="",
-        expected = {"number": "", "date": "", "type": "", "type_code": "", "kind": "", "currency": "",
+        expected = {"number": "", "date": "", "type": "", "type_code": w.active, "kind": "", "currency": "",
```

Test SHA256: до `4dd129e23d0317a31d1446900aeed259c664c1c3c5be596d79a057e82716cbf2`, после `9e869985cb574f2dd26ced6d63377b715d1ce7e64618fb41b5333c4f514f20d6`; новый Git blob `ab898463858ab6a16734fda81805b6da5587db8a`. Полные source paths/ranges/file SHA256/span SHA256 — в [парном JSON](CONTRACT_CARD_TYPE_CODE_PORTABILITY_20261101.json).

Stdlib AST восстановил весь parent test module после обращения ровно этих двух изменений; независимая byte-проверка требует только две буквальные замены строк. card_values, guards/fixtures/helpers, production32-field mapping, null/zero/False и остальные empty поля сохранены. Git source diff не показывает других изменений старых paths; production/native/shared/schema/SDK/config/CI/flags и прежние отчёты не менялись. Статически5 функций/10 cases, старый native16/55, без collection. Никаких app/helper/test imports, runtime, SQL, pytest, compile/codegen/build/CI или network: **NOTRUN**. Обычный pytest не разрешён: будущий ROOT runner обязан проверить target/source до conftest/imports.

Полные20M/11 остаются в frozen PR95 и не сокращаются/не закрываются:

- [Исходный MD](CONTRACT_CARD_CREATION_PREREQUISITE_20261101.md), SHA256 `fbe295e31c83f5536cfaf6073e932a4b24e933f98558f7c63ed769047b9ca2f3`.
- [Исходный JSON](CONTRACT_CARD_CREATION_PREREQUISITE_20261101.json), SHA256 `324a459fa5bf191d488c45425a72c7c6f760de6e2e981eb9b12be7b1eda203d0`.

Shared SHA256 `9a18628d5e6f701dab13c30fced65ef711ce8aa3d7fef4a0ae51ecf8cf5b4158`; native `9a8f88d0b5bb539a19c596a374e786d5f00be672f489625be4066557a71f49e4`; старый native test `bf4cf2d7c22d478c2235aaead82e208bab84a4c31be3c95524c200c089152408` — без изменения. Runtime acceptance, полный CREATE/SDK и отдельный draft PR остаются у ROOT/координатора.
