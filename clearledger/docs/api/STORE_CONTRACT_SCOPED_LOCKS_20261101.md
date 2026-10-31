# Store → scoped locks: только SOURCE

База PR100 `8b512be5f54bc88340dfd0d20ff8129f829cb0cc`.
Зависимость exact5 PR98 `18d9061f5a9fa6671c128f3ad97d77490360f3cc` неизменна.

Save и mixed partner+contract получают полный Company SHARED + RefComposite
EXCLUSIVE до legacy CP → contract и любых ref writes. Ключи берутся из
проверенного сервером access.company_id (UUID). Prepared передаётся явно;
body/claims не дают authority. require_scoped_locks(db.sync_session,
capability, requiredtuple) проверяет issuer/root/connection/coverage до мутаций
и после await. Нет late acquire, reentry, upgrade, retry или plan expansion.
Root и commit/rollback остаются у caller; Company перечитывается после B.

Clean entry отвергает new/dirty/deleted до чтения. Access/INN discovery идут
под no_autoflush. После ВСЕХ B/legacy barriers clean состояние проверяется снова:
точные retained Contract/Counterparty/Organization получают полный instance
expiry, чтобы общий matcher/validator загрузил текущие строки. Это только ранняя
граница подготовки; later authorized CP/title/raw pending не очищаются.
UPDATE target по-прежнему читается с populate_existing.

Пустой/отсутствующий договор идёт прежним CP-only путём без B. Ранний INN-ответ
сохранён. Общие creator/matcher/validator PR100 не заменены. Преобразования,
null/falsy/defaults, tenant, raw/manual_overrides, retained UPDATE cp/org/type,
exclude-self409 и различие неполных identity сохранены.

Авторские PG schedules: реальные Store callers/helper, pg_locks/blocking_pids,
strong retained candidate/target/parties через реальный wait и T2 commit,
текущие409/400/404 до мутаций; stale/foreign/partial caps, poison и pending.
Unused refs удаляются существующими DELETE с их usage/FK prerequisites;
несуществующий tenant-move API не предполагается. Отдельный конкурент будущего
CREATE синтетический (Company SHARED + RefComposite SHARED), не HTTP CREATE.
Прежние regression assertions сохранены; unit doubles не доказывают B.

**Все NOTRUN**, включая imports/collection. ROOT проверяет отдельную одноразовую
БД/схему/isolated executor ДО imports. Guards не защищают от раннего destructive
conftest; runner не добавлен. STORE-B-R1 исправлен на SOURCE, recheck ожидается.

KNOWN_DEPENDENCY_RUNTIME_BLOCKER: ROOT сообщил сбой helper18d в composition
OptionEngine(schema_translate_map): event.listen Connection(commit), nested
joined dispatch SQLAlchemy2.0.36. Нами не исполнялось; fix у helper owner,
helper5 остаются frozen18d. Runtime held независимо от SOURCE verdict.

Объём: Company/ref mixed roots. Full Store account-authority linearization и
entire B OPEN. Прежняя гонка INN до lock, отсутствие under-lock recheck и
different-CP matcher остаются отдельным OPEN P1. CREATE OFF. M00–M19 и все11
условий OPEN. Runtime/рабочие данные/merge/deploy GO не разрешены.
