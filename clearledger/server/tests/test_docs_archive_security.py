import uuid
from datetime import date
from types import SimpleNamespace

from app.main import app
from app.models import DocAccessGrant, DocDestructionAct, DocDestructionItem
from app.routers import docs_router
from app.services import doc_archive
from app.services import mail_send


def _doc(**values):
    defaults = {
        "status": "archived",
        "retention_state": "archived",
        "storage_until": date(2024, 12, 31),
        "retention_extended_until": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_уничтожение_доступно_только_после_границы_первого_января():
    today = date(2026, 8, 17)
    assert doc_archive.destruction_blocker(
        _doc(storage_until=date(2025, 12, 31)), [], today,
    ) is None
    assert "1 января" in doc_archive.destruction_blocker(
        _doc(storage_until=date(2026, 1, 1)), [], today,
    )


def test_hold_и_постоянное_хранение_блокируют_уничтожение():
    today = date(2026, 8, 17)
    assert "запрет" in doc_archive.destruction_blocker(
        _doc(), [SimpleNamespace(id=uuid.uuid4())], today,
    )
    assert "не допускает" in doc_archive.destruction_blocker(
        _doc(retention_state="permanent"), [], today,
    )
    assert "прежней версии" in doc_archive.destruction_blocker(
        _doc(retention_state="legacy_review"), [], today,
    )


def test_продление_не_переписывает_исходный_срок():
    doc = _doc(
        storage_until=date(2024, 12, 31),
        retention_extended_until=date(2030, 12, 31),
    )
    assert doc_archive.effective_until(doc) == date(2030, 12, 31)
    assert doc.storage_until == date(2024, 12, 31)


def test_snapshot_hash_каноничен():
    assert doc_archive.snapshot_hash({"b": 2, "a": {"x": 1}}) == (
        doc_archive.snapshot_hash({"a": {"x": 1}, "b": 2})
    )


def test_deny_read_перекрывает_любое_контентное_право():
    user_id = uuid.uuid4()
    row = DocAccessGrant(
        company_id=uuid.uuid4(), scope_type="doc", scope_id=uuid.uuid4(),
        subject_type="user", subject_id=user_id,
        permissions=["download", "edit"], denied_permissions=["read"],
    )
    subjects = {"user": user_id, "role": None, "department": None}
    assert docs_router._denied([row], subjects, "read")
    assert docs_router._denied([row], subjects, "download")
    assert docs_router._denied([row], subjects, "edit")
    assert not docs_router._denied([row], subjects, "manage_acl")


def test_deny_другого_субъекта_не_затрагивает_пользователя():
    row = DocAccessGrant(
        company_id=uuid.uuid4(), scope_type="doc", scope_id=uuid.uuid4(),
        subject_type="user", subject_id=uuid.uuid4(),
        permissions=[], denied_permissions=["download"],
    )
    subjects = {"user": uuid.uuid4(), "role": None, "department": None}
    assert not docs_router._denied([row], subjects, "download")


def test_break_glass_не_разрешает_изменение_или_отправку():
    assert docs_router._BREAK_GLASS_PERMISSIONS == {"read", "download", "print"}


def test_активный_акт_не_дублирует_документ():
    index = next(item for item in DocDestructionItem.__table__.indexes
                 if item.name == "uq_doc_destruction_items_active_doc")
    assert index.unique is True
    assert "primary_purged" in str(index.dialect_options["postgresql"]["where"])


def test_черновик_акта_можно_отменить_без_потери_истории():
    act_checks = " ".join(str(item.sqltext) for item in
                          DocDestructionAct.__table__.constraints
                          if hasattr(item, "sqltext"))
    item_checks = " ".join(str(item.sqltext) for item in
                           DocDestructionItem.__table__.constraints
                           if hasattr(item, "sqltext"))
    assert "cancelled" in act_checks
    assert "cancelled" in item_checks


def test_статические_archive_маршруты_раньше_карточки():
    paths = [route.path for route in app.routes]
    assert paths.index("/api/docs/archive/queue") < paths.index("/api/docs/{doc_id}")
    assert paths.index("/api/docs/archive/acts") < paths.index("/api/docs/{doc_id}")


def test_отказ_подключения_smtp_не_выдаётся_за_неизвестную_доставку():
    from aiosmtplib.errors import SMTPConnectError, SMTPReadTimeoutError

    assert not mail_send.delivery_outcome_unknown(
        SMTPConnectError("connection refused"),
    )
    assert mail_send.delivery_outcome_unknown(SMTPReadTimeoutError("timeout"))
