# Совместный состав Docs logout и UUID

SOURCE подготовлен ROOT; runtime проверки Docs ещё NOTRUN.

Исходный DPL7a84 сохраняет19 записей PROTECTED_BYTES от bf741. ROOT ранее принял
UUID29baa0c6 после независимого SOURCE+RAW:38 UUID/1С и162 native сценария.
Этот разрешённый шаг меняет три защищённых model файла. Для совместной
композиции тест явно сохраняет прежние baseline SHA и проверяет только точные
новые SHA трёх моделей из UUID29b. Остальные guards остаются прежними.
Дополнительно закреплены четыре support файла того же принятого UUID Source:
db_types, models_partner_contracts, product queries и counterparty usage.

Это не пропуск теста или вычисление ожидаемых значений из текущего рабочего
дерева. Литералы выведены из двух неизменяемых Git commit и сверены ROOT;
индивидуальные before/after pins находятся в парном JSON. Производственные
DPL обработчики, все17 прежних ветвей и12 canonical policies не изменены.
Исходные17 PG определений DPL не менялись. Приёмка прошлых38/162 не считается
прохождением нового совместного состава: нужны отдельный ROOT admission,
реальные HTTP/public verifier/cookie/CSRF/waits/rollback/fresh-reader проверки.

Полные20 разделов и11 требований сохраняются; merge/выкатка/flags не выполнялись.
