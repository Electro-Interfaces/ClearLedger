# MemberScope: prerequisite Org FK

P1 добавляет `RefCompositeKey(company) S` только в полный initial B
`set_member_scope`. `scope_org=False` сохраняет прежний план остальных
15 корней. Company/User/Role/Member modes прежние, self объединяется upfront.
Ключи strict UUID не меняются; общая ORM UUID subclass зависимость OPEN.

Discovery: clean `no_autoflush`, actual homes/roles/existence/old ownOrg,
proposed Org owner. После B: Company → User → Role, readonly admission,
scoped proposed Org SHARE → все Member rows. Известные ACL/member404 ошибки
не ждут Org. Foreign old Org не блокируется. После всех ожиданий и object
SELECT перечитываются pointers, slug→тот же UUID, proposed Org и native
JWT/session/token-version/visit/admin. Drift родителей/old pointer даёт 409
всего root, без late keys, retry или discard. Новый effective SET после
Org-фазы вне фактически row-locked candidate тоже даёт 409 до записи;
RETAIN и disappearing/foreign CLEAR исключены из этого сравнения. Capability проверяется после
ожиданий, перед setters, audit и commit.

Org null/omitted сохраняют old, включая foreign legacy. Empty, whitespace,
invalid UUID, missing и foreign proposed очищают None; valid same-company
задаёт Org. Object null/omitted/[] дают None («вся сеть»); opaque чужие IDs
молча фильтруются по company. Все Org/object reads завершены до setters.
Прежние action/target/details, explicit commit и response сохранены.
Audit background dispatch до commit не стал outbox-гарантией.

Unit/PG определения **NOTRUN**, включая collection. Сделаны только статические
AST/compile без исполнения, hash и scope проверки. Для runtime нужны
изолированный conftest, одобренная synthetic PG и общее UUID-решение;
локальных casts, driver patches и искусственных skips нет.

OrgDELETE **OPEN**, его код не изменён. RefX-peer проверяет только будущий
барьер, не actual delete. Будущему delete нужны все Member referrers без
company filter, их companies/home Users, upfront Member X + RefX и полное
postwait set comparison. Inflight/phantom closure этим P1 не доказана.
Documents/TP/DocCase/archive sealed trigger/shared files/profile и softrefs
требуют отдельных владельцев и физической FK/trigger-приёмки.

JSON рядом хранит подробный контракт, NOTRUN acceptance и полный исходный
состав программы: 20 разделов и 11 сквозных условий, все OPEN.
