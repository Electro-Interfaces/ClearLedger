# Переход wrapup → postcall, support-context/1

Нормативное additive уточнение ошибок и клиентского перехода от 21.10.2026.
C02 body/JWT/scopes и hard deadlines не расширяются. Основание: actual V20
natural-A.json на Node47b/Support10cdb/Core133, msg_bc06fb21f5e6.

JWT exp имеет целые секунды и может истечь до дробного Node phaseDeadline.
Пока Node законно остаётся wrapup, отсутствие ended ещё не доказывает отзыв.
После проверки неизменной call/context/actor/assignment/admission/key связи,
отсутствия explicit revoke, текущих Core/Support прав и назначения заявки
первый postcall может ответить HTTP409 с error.code=postcall_pending,
error.retryable=true. Такой ответ не выдаёт grant, действий или данных.
Он не фиксирует/продлевает postcallDeadline и не изменяет исходный grant.
Истечение live wrapup phaseDeadline или active=false без explicit revoke
не превращает первоначальное ожидание ended в окончательный отзыв: это может
быть интервал обновления Node-проекции, включая переход во время ACL HTTP.
Pending сохраняет только ожидание, без live-действий; Context TTL, текущие Core/Support
права/назначение, MFA и уже закреплённый hard postcall deadline остаются обязательными.

Код применим только к первоначальному переходу из допустимого wrapup,
до уже закреплённого postcall права. Нарушенная связь, отзыв, смена роли/назначения,
expired hard deadline и откат Node из ended после выданного postcall остаются
окончательным отказом. Проверка Node ended/endedAt и все current ACL обязательны
перед выдачей ticket-only grant; expiry live JWT не округляется вверх и не продлевается.

Клиент при истечении live exp сразу скрывает/очищает dossier и прекращает
действия по истёкшему допуску. При явном postcall_pending он сохраняет тот же
iframe/nonextractable key и допустимую локальную работу, выполняет ограниченный
повтор с новыми DPoP proof. После bounded automatic retry может показывать
временный статус/ручную повторную проверку без выдачи прав и без ложного success.
Окончательный отказ/смена actor/finish очищают чувствительный cache/draft/key.
Только положительный новый grant разрешает ticket.read/append; profile/charging/create
после разговора не восстанавливаются. Work pending остаётся boolean, не авторизацией.

Core и Support UI фиксы проверяются раздельно и затем настоящей естественной
Node timer последовательностью V20, без SQL phase/fake-clock/wait-after-ended обхода.
