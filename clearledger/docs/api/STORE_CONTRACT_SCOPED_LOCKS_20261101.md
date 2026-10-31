# Store → scoped locks: только SOURCE

База PR100: `8b512be5f54bc88340dfd0d20ff8129f829cb0cc`.
Зависимость: exact5 PR98 `18d9061f5a9fa6671c128f3ad97d77490360f3cc`, без правок.

Save и mixed partner+contract получают единый полный план Company SHARED +
RefComposite EXCLUSIVE до legacy CP → contract и любых записей справочников.
Ключи строятся из проверенного сервером access.company_id (UUID).
PreparedStoreContractWrite передаётся явно, тело запроса не даёт authority.
require_scoped_locks(db.sync_session, capability, requiredtuple) проверяет
настоящие issuer/root/connection/coverage до мутаций и после await. Нет late
acquire, extension, reentry, upgrade, внутренних commit/rollback/retry.
Root завершает caller; Company перечитывается после ожидания B.

New/dirty/deleted отвергаются до discovery; access и поиск ИНН идут под
no_autoflush. Пустой/отсутствующий договор сохраняет CP-only путь без B.
Ранний ответ по существующему ИНН сохранён. Общие creator/matcher/validator,
преобразования, null/falsy/defaults и tenant-правила PR100 не заменены.
UPDATE сохраняет cp/org/type, raw/manual_overrides, исключает себя из
complete-identity409; неполные identity остаются различными.

Авторские PG-сценарии используют реальные Store callers и helper: оба
направления ожидания, pg_locks/blocking_pids, stale/foreign/forged/partial caps,
poison, pending до чтения, отсутствие договора и legacy-порядок. Конкурент
будущего CREATE синтетический: Company SHARED + RefComposite SHARED;
действующего HTTP CREATE это не доказывает. Прежние regression assertions
сохранены; unit doubles не считаются доказательством B.

**Все NOTRUN**, включая imports/collection. ROOT отдельно проверяет одноразовую
БД, схему и состав исполнения ДО imports. Module guards не защищают от раннего
destructive conftest; runner не добавлен.

Объём: участие Company/ref mixed roots. Полная линеаризация отзыва Store
account-authority и entire B остаются OPEN. Прежняя гонка INN до lock, отсутствие
повторной проверки INN под lock и different-CP matcher остаются отдельным OPEN
P1, здесь не исправлены. CREATE OFF. M00–M19 и все 11 условий программы OPEN.
Runtime/рабочие данные/merge/deploy GO не разрешены.
