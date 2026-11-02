# Swagger: ограниченная функциональная приёмка native24 · 01.11.2026

На Source `7e988068f768ba424ebebb0d11b5caea051cbfbb` независимо сверены
исходники и результаты24 разных случаев в двух отдельных PostgreSQL-средах.
Функциональная приёмка ограничена этими сценариями. Первый полный запуск
сохраняет FAIL контроля общего окружения; общего CI24 и полного M11 PASS нет.

| Серия | Случаи / определения | Успешные фазы | pytest / внешний процесс | Время с подготовкой |
|---|---:|---:|---|---:|
| HappyV3 | 1 / 1 | 3 | 0 / 1: GLOBAL foreign parity FAIL | 37,512с |
| Rest23V2 | 23 / 8 | 69 | 0 / 0 | 134,023с |

Объединение выборок равно24 исходным случаям, без пересечения. Более ранний
повтор того же happy-case повторно не посчитан. Рецензент не запускал код;
Root повторно сверил46pins. [Машинная сводка](PARTNER_DOCS_PORTAL_NATIVE24_ROOT_VERIFICATION_20261101.json)
закрепляет Source, хеши review, результаты и ограничения.

## Проверенное поведение

Обычный сотрудник и membership имеют role=user, superadmin=false. Начальный
native JWT создан штатным `auth.token_for`; парольного login здесь нет.
Штатные Authlib authorize/consent/Code+PKCE/token и настоящие SQL проверяют
grant/user/installation, S256, потребление code, RS256 issuer/audience/nonce.
Далее создаётся SQL docs-cookie: Secure/HttpOnly/SameSite=Strict, ограниченный
Path, срок не больше срока access token и180секунд, без bearer в cookie.

Через ASGI получены8 защищённых surfaces: UI, обе OpenAPI-проекции,
четыре JS/CSS-ресурса и OAuth redirect. В browser/server схемах проверены
ровно17 операций, server URL и отдельная security projection: browser
публикует authorizationCode, машинный профиль сохраняется в server-схеме.
Это получение байтов, без запуска JavaScript и браузерной проверки Swagger.

Отрицательные сценарии проверяют bearer вместо cookie, пять неверных
параметров authorize, привязку code к verifier/redirect, изменение membership
и роли между страницей consent и approve, отзыв grant/member/client/install/
mail_only/token_version, machine bootstrap и logout с Origin/CSRF. После
отзыва существующая cookie и повторный docs-session bootstrap закрываются;
новый code-token exchange после отзыва отдельным случаем не проверялся.

Четыре product-denial случая используют реальный положительный objects:read
ответ200, положительную coarse CREATE проверку и валидное тело. Отказ
docs-cookie/docs-token проверен как401/403 с Problem и заголовками, без
ложноположительного422. Успешный product POST или полный write-policy этим
не доказан. Отсутствие побочных записей ограничено счётчиками пяти выбранных
множеств, не равенством всех полей всех строк.

## Окружение и сохранённые ошибки

В каждом мире579файлов совпали с frozen Git и manifest. Использованы native
341/347, валидированные FK/RI, обычная роль без повышенных прав, factory8 и
READ COMMITTED. Записаны реальные агрегаты SQL shapes без параметров;
выводы о конкретных значениях и порядке опираются на неизменённые прошедшие
assertions, отдельной HTTP-body/хронологической SQL трассы нет. Внешние байты
helper/dependencies рецензент не перечитывал.

HappyV3: исходные42 безопасные строки посторонних контейнеров не изменились,
появились3 новых ID вне двух owned ID. Строгая GLOBAL parity42→45 остаётся
FAIL/HOSTEXIT1; авторство и назначение новых объектов этим не устанавливаются.
Оба своих контейнера удалены, пулы/клиенты/блокировки0. Rest23 имеет точную
parity43→43 и такую же очистку; внешний exit0 подтверждён наблюдением Root,
без отдельной файловой argv-квитанции. Временные изменения между снимками
не исключены. Остатки базового issuer_world принадлежали целиком уничтоженной
синтетической БД; будущая очистка при отмене не сертифицирована.

Первый setup на681 завершился SQLSTATE22001: App.code45 при лимите40,
selected1/testsRun0, OAuth не выполнялся. Правка7e меняет только seed App.code
на37символов; client IDs37/45, схема, сервисы и oracles сохранены. Более ранний
happy имел functionalPASS с внешнимFAIL и отсутствующей исходной final-квитанцией;
поздняя reconciliation не восстанавливает её. Ошибка подготовки RestV1
SyntaxError до collection также сохранена. Эти результаты не названы PASS.

Старый `test_docs_portal.py` уже использовал настоящую PostgreSQL/Authlib и
admin membership; новый пакет добавляет ordinary employee и текущие17операций.
Его приёмка не означает повторный успех старого набора.

Review MD SHA-256: `8ab67613b1b03d86c19aa037701c5dc094885dbffa09d2bb225e825905f0859a`.
Review JSON SHA-256: `58d37f170ee0f0d9fafcf63da349f4c49c4eea48a9eb7116a6763047b4351aa4`.

Браузер/Try it out, ingress/CORS, SSO, реальный партнёр, общий окончательный
состав и вся программа M00–M19+11 остаются открыты. Merge, выкатка и изменение
рабочих флагов не выполнялись.
