"""Предметные данные ТП. Не двигает стадии проекта и не заменяет службу процессов.

Изменения сериализуются блокировкой площадки; версия защищает черновик пользователя.
Оповещения записываются в штатный чат вместе с подтверждением доставки одной транзакцией.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.models import (EzsSite, EzsTechConnection, Organization, SourceFile,
                        TpOrganizationDocument, User, UserCompany)
from app.services import ezs_tp_steps


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Responsibility(Strict):
    executor: uuid.UUID | None = None
    controller: uuid.UUID | None = None
    provider: uuid.UUID | None = None
    due: date | None = None


class Remark(Strict):
    id: uuid.UUID
    branch: Literal["application", "inspection", "supply"] = "application"
    text: str = Field(min_length=1, max_length=2000)
    received: date
    due: date | None = None
    resolved: date | None = None
    response: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def chronology(self):
        if self.resolved and (self.resolved < self.received or not self.response.strip()):
            raise ValueError("Для снятия замечания нужны дата не раньше получения и описание ответа")
        if self.due and self.due < self.received:
            raise ValueError("Срок ответа не может предшествовать замечанию")
        return self


class WorkStage(Strict):
    id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    contractor: str = Field(default="", max_length=300)
    due: date | None = None
    done: date | None = None
    notified: date | None = None
    accepted: date | None = None
    executor: uuid.UUID | None = None
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def chronology(self):
        if self.notified and (not self.done or self.notified < self.done):
            raise ValueError("Сначала выполните этап, затем уведомите сетевую")
        if self.accepted and (not self.notified or self.accepted < self.notified):
            raise ValueError("Приёмка этапа не может предшествовать уведомлению")
        return self


class Workflow(Strict):
    process_enabled: bool = False
    emergency_automation: bool = False
    design_required: bool = False
    scenario: Literal["new", "increase", "redistribution"] = "new"
    organization_id: uuid.UUID | None = None
    supply_mode: Literal["landlord", "direct", "via_grid", "existing"] = "landlord"
    supply_contract_id: uuid.UUID | None = None
    representative: bool = False
    apartment_building: bool = False
    personal_data_consent: Literal["pending", "portal", "file"] = "pending"
    design_date: date | None = None
    commissioning_date: date | None = None
    responsibilities: dict[str, Responsibility] = Field(default_factory=dict, max_length=30)
    remarks: list[Remark] = Field(default_factory=list, max_length=100)
    stages: list[WorkStage] = Field(default_factory=list, max_length=100)
    # Подтверждение содержания не подменяется фактом загрузки файла.
    reviewed_kinds: list[str] = Field(default_factory=list, max_length=30)
    review_note: str = Field(default="", max_length=2000)
    additional_requirements: list[str] = Field(default_factory=list, max_length=20)
    archived: bool = False

    @model_validator(mode="after")
    def unique_ids(self):
        for items in (self.remarks, self.stages):
            if len({x.id for x in items}) != len(items):
                raise ValueError("Повторяется идентификатор строки")
        if set(self.responsibilities) - (set(ezs_tp_steps.STEP_BY_KEY) | {"default"}):
            raise ValueError("Неизвестный шаг ответственности")
        return self


class SaveWorkflow(Strict):
    version: int = Field(ge=0)
    evidence_token: str | None = None
    data: Workflow


SCENARIOS = {"new": "Новое присоединение", "increase": "Увеличение мощности",
             "redistribution": "Перераспределение мощности"}
DOC_LABELS = {
    "tp_layout": "План расположения энергопринимающих устройств",
    "tp_single_line": "Однолинейная схема электрических сетей",
    "tp_automation": "Перечень устройств противоаварийной автоматики",
    "tp_external_scheme": "Согласованная схема внешнего электроснабжения",
    "tp_design": "Разделы проектной документации по выполнению ТУ",
    "tp_tests": "Протоколы пусконаладочных и приёмо-сдаточных испытаний",
    "tp_circuit": "Нормальная схема электрических соединений",
    "contract": "Право на участок / помещение", "egrul": "Выписка ЕГРЮЛ",
    "poa": "Доверенность представителя", "tp_indirect": "Соглашение об опосредованном ТП",
    "tp_power_share": "Соглашение о перераспределении мощности",
    "tp_consent": "Согласие на обработку персональных данных",
    "tp_building_consent": "Согласие на присоединение помещения в здании",
    "tp_existing_act": "Документы о ранее присоединённой мощности",
    "tp_supply_draft": "Проект договора со сбытом / протокол разногласий",
    "tu": "Технические условия", "tp_contract": "Договор ТП", "tp_act": "Акт ТП",
    "tp_avtu": "Акт выполнения ТУ", "tp_meter_act": "Акт допуска узлов учёта",
    "power_contract": "Договор электроснабжения",
}
SHARED_KINDS = {"egrul", "poa", "tp_consent", "counterparty_card"}


def data_of(tc):
    return Workflow.model_validate({k: v for k, v in (tc.workflow or {}).items() if not k.startswith("_")})


def required_kinds(tc, w):
    kinds = []
    if tc.method in ("direct", "indirect"):
        kinds = ["contract", "egrul", "tp_layout"]
        from app.services.ezs_tp_method import capacity_profile
        profile = capacity_profile(tc)
        if (profile["voltageKv"] or 0) >= 35: kinds.append("tp_single_line")
        if (profile["totalKw"] or 0) > 50000: kinds.append("tp_external_scheme")
        if w.emergency_automation: kinds.append("tp_automation")
        if tc.method == "indirect": kinds.append("tp_indirect")
        if w.scenario != "new": kinds.append("tp_existing_act")
        if w.scenario == "redistribution": kinds.append("tp_power_share")
        if w.representative: kinds.append("poa")
        if w.apartment_building: kinds.append("tp_building_consent")
        if w.personal_data_consent == "file": kinds.append("tp_consent")
        if w.supply_mode == "via_grid": kinds.append("tp_supply_draft")
    return list(dict.fromkeys(kinds + w.additional_requirements))


def supply_kinds(tc, w):
    if w.supply_mode in ("landlord", "existing"): return []
    result = ["contract", "egrul", "tp_meter_act"]
    result.append("tp_avtu" if tc.method in ("direct", "indirect") else "tp_existing_act")
    if w.representative: result.append("poa")
    return result


def outstanding(tc, w, kinds):
    missing = [DOC_LABELS.get(k, k) for k in required_kinds(tc, w) if k not in kinds]
    if tc.method in ("direct", "indirect"):
        from app.services.ezs_tp_method import capacity_profile
        if capacity_profile(tc)["voltageKv"] is None: missing.append("Уточните класс напряжения в кВ")
        if not w.organization_id: missing.append("Заявитель")
        if not tc.grid_operator: missing.append("Сетевая организация")
        if tc.power_kwt is None or tc.power_kwt <= 0: missing.append("Запрашиваемая мощность")
        if w.scenario != "new" and not tc.existing_power_kwt: missing.append("Ранее присоединённая мощность")
        if w.personal_data_consent == "pending": missing.append("Согласие на обработку персональных данных")
        if not w.design_date or not w.commissioning_date: missing.append("Сроки проектирования и ввода")
        if not tc.energy_supplier: missing.append("Сбытовая организация")
    return missing


def remarks_out(w, today=None):
    today = today or date.today()
    return [dict(r.model_dump(mode="json"), deadline=(r.due or (
        r.received + timedelta(days=20) if r.branch == "application" else r.received)).isoformat(),
        overdue=not r.resolved and (r.due or (r.received + timedelta(days=20)
                  if r.branch == "application" else r.received)) < today) for r in w.remarks]


def final_missing(tc, w, kinds):
    missing = []
    if not tc.method: missing.append("Способ присоединения")
    if tc.method in ("direct", "indirect"):
        for k in ("tu", "tp_contract", "tp_act", "tp_avtu", "tp_meter_act"):
            if k not in kinds: missing.append(DOC_LABELS[k])
        from app.services.ezs_tp_method import capacity_profile
        profile = capacity_profile(tc)
        completion = []
        if w.design_required: completion.append("tp_design")
        if (profile["totalKw"] or 0) > 670 and (profile["voltageKv"] or 0) > 1:
            completion += ["tp_tests", "tp_circuit"]
        for k in completion:
            if k not in kinds: missing.append(DOC_LABELS[k])
        if not tc.done_date: missing.append("Дата завершения ТП")
        if any(not x.accepted for x in w.stages): missing.append("Приёмка всех этапов ТУ")
    if w.supply_mode != "landlord":
        if not w.supply_contract_id and "power_contract" not in kinds: missing.append("Договор электроснабжения")
        if w.supply_mode != "existing" and not (tc.steps or {}).get("supply_contract", {}).get("date"):
            missing.append("Дата заключения договора электроснабжения")
    if any(not r.resolved for r in w.remarks): missing.append("Снятие замечаний")
    return missing


async def evidence(db, tc, w):
    from app.models import EzsSiteDoc
    from app.services.ezs_site_work import site_doc_kinds
    kinds = await site_doc_kinds(db, tc.site_id)
    # Старый общий чек-лист засчитывает пустую карточку; для ТП нужен сам файл.
    local = (await db.execute(select(EzsSiteDoc).where(EzsSiteDoc.site_id == tc.site_id,
                                                      EzsSiteDoc.company_id == tc.company_id))).scalars().all()
    empty = {x.kind for x in local if not x.file_id} - {x.kind for x in local if x.file_id}
    kinds -= empty
    signatures = {k: sorted(str(x.file_id) for x in local if x.kind == k and x.file_id) for k in kinds}
    shared = []
    if w.organization_id:
        rows = (await db.execute(select(TpOrganizationDocument, SourceFile.file_name)
            .join(SourceFile, SourceFile.id == TpOrganizationDocument.file_id)
            .where(TpOrganizationDocument.company_id == tc.company_id,
                   SourceFile.company_id == tc.company_id,
                   TpOrganizationDocument.organization_id == w.organization_id))).all()
        for d, name in rows:
            expired = bool(d.valid_until and d.valid_until < date.today().isoformat())
            shared.append(dict(id=str(d.id), kind=d.kind, name=name, expired=expired,
                               validUntil=d.valid_until, fileId=str(d.file_id)))
            if not expired:
                kinds.add(d.kind)
                signatures.setdefault(d.kind, []).append(str(d.file_id))
    return kinds, shared, {k: sorted(v) for k, v in signatures.items()}


def evidence_token(signatures):
    return hashlib.sha256(json.dumps(signatures, sort_keys=True).encode()).hexdigest()


async def read(db, tc):
    w = data_of(tc)
    kinds, shared, signatures = await evidence(db, tc, w)
    required = required_kinds(tc, w)
    missing = outstanding(tc, w, kinds)
    valid_reviews = {k for k in w.reviewed_kinds if
                     (tc.workflow or {}).get("_review_files", {}).get(k) == signatures.get(k)}
    unreviewed = [k for k in required if k not in valid_reviews]
    public_data = w.model_dump(mode="json")
    public_data["reviewed_kinds"] = sorted(valid_reviews)
    from app.services.ezs_tp_method import capacity_profile, handover_state
    return dict(profile=capacity_profile(tc), process=(tc.workflow or {}).get("_process", {}),
                handover=await handover_state(db, tc),
                version=tc.workflow_version or 0, data=public_data, evidenceToken=evidence_token(signatures),
                scenarios=SCENARIOS, documentKinds=DOC_LABELS,
                kit=[dict(kind=k, label=DOC_LABELS.get(k, k), present=k in kinds,
                          reviewed=k in valid_reviews) for k in required],
                supplyKit=[dict(kind=k,label=DOC_LABELS[k],present=k in kinds,reviewed=k in valid_reviews) for k in supply_kinds(tc,w)],
                supplyComplete=bool(w.supply_mode == "existing" and w.supply_contract_id) or
                    bool(w.supply_mode not in ("landlord", "existing") and
                         (tc.steps or {}).get("supply_contract", {}).get("date") and
                         (w.supply_contract_id or "power_contract" in kinds) and
                         not any(not x.resolved and x.branch == "supply" for x in w.remarks)),
                supplyReady=bool(w.supply_mode == "existing" and w.supply_contract_id) or
                    bool(w.supply_mode not in ("landlord", "existing") and tc.energy_supplier and
                         all(k in kinds and k in valid_reviews for k in supply_kinds(tc,w))),
                sharedDocuments=shared, missing=missing,
                ready=bool(tc.method in ("direct", "indirect") and not missing and not unreviewed),
                remarks=remarks_out(w), finalMissing=final_missing(tc, w, kinds),
                notifications=(tc.workflow or {}).get("_delivery", {}))


async def validate_refs(db, tc, w):
    from app.models import Contract
    site = await db.get(EzsSite, tc.site_id)
    if w.organization_id:
        org = await db.get(Organization, w.organization_id)
        if not org or org.company_id != tc.company_id: raise HTTPException(400, "Заявитель не принадлежит компании")
    if w.supply_contract_id:
        contract = await db.get(Contract, w.supply_contract_id)
        if not contract or contract.company_id != tc.company_id:
            raise HTTPException(400, "Договор не принадлежит компании")
        if contract.type != "energy":
            raise HTTPException(400, "Выберите договор энергоснабжения")
        if w.organization_id and contract.organization_id != w.organization_id:
            raise HTTPException(400, "Договор оформлен на другое юрлицо")
    people = {x for r in w.responsibilities.values() for x in (r.executor, r.controller, r.provider) if x}
    people |= {x.executor for x in w.stages if x.executor}
    for person in people:
        u = await db.get(User, person)
        member = await db.get(UserCompany, (person, tc.company_id))
        if member and member.role != "admin" and member.object_scope and str(site.location_id) not in member.object_scope:
            raise HTTPException(400, "У назначаемого участника нет доступа к объекту проекта")
        if member and member.own_organization_id and member.own_organization_id != w.organization_id:
            raise HTTPException(400, "Участник ведёт другое юрлицо")
        if not u or not member or u.mail_only:
            raise HTTPException(400, "Назначить можно только участника этой компании с доступом в пространство")
    if set(w.additional_requirements + w.reviewed_kinds) - set(DOC_LABELS):
        raise HTTPException(400, "Неизвестный вид документа")


async def save(db, tc, payload, user):
    if payload.version != (tc.workflow_version or 0):
        raise HTTPException(409, "Присоединение изменено другим пользователем. Обновите данные и повторите правку")
    w = payload.data
    await validate_refs(db, tc, w)
    if w.process_enabled:
        default = w.responsibilities.get("default", Responsibility())
        if not tc.method or not w.organization_id or not all((default.provider, default.executor, default.controller)):
            raise HTTPException(400, "Для запуска методики выберите способ, заявителя, поставщика данных, исполнителя и контролирующего")
    kinds, _, signatures = await evidence(db, tc, w)
    if w.reviewed_kinds and payload.evidence_token != evidence_token(signatures):
        raise HTTPException(409, "Состав файлов изменился. Обновите комплект и проверьте новые документы")
    if set(w.reviewed_kinds) - kinds:
        raise HTTPException(400, "Нельзя подтвердить содержание отсутствующего документа")
    if w.archived and not any(r.controller for r in w.responsibilities.values()):
        raise HTTPException(400, "Назначьте контролирующего для передачи итоговых документов")
    if w.archived:
        missing = final_missing(tc, w, kinds)
        if missing: raise HTTPException(400, "Не готово к архиву: " + "; ".join(missing))
    old = copy.deepcopy(tc.workflow or {})
    if old.get("archived") and w.archived and w.model_dump(mode="json") != data_of(tc).model_dump(mode="json"):
        raise HTTPException(409, "Сначала снимите отметку завершения, чтобы изменить архивный комплект")
    tc.workflow = dict({k: v for k, v in old.items() if k.startswith("_")}, **w.model_dump(mode="json"), _delivery=old.get("_delivery", {}),
                       _review_files={k: signatures.get(k, []) for k in w.reviewed_kinds})
    if not w.archived:
        if old.get("_handover") and old.get("archived"):
            from app.models import DocAcquaint
            pending = (await db.execute(select(DocAcquaint).where(
                DocAcquaint.company_id == tc.company_id,
                DocAcquaint.doc_id == uuid.UUID(old["_handover"]["docId"]),
                DocAcquaint.status == "pending"))).scalars().all()
            for row in pending: row.status = "superseded"
        tc.workflow.pop("_archive", None)
        tc.workflow.pop("_handover", None)
    if w.archived:
        tc.workflow["_archive"] = old.get("_archive") or {
            "at": datetime.now(timezone.utc).isoformat(), "by": str(user.id),
            "files": signatures, "site_id": str(tc.site_id)}
    tc.workflow_version = (tc.workflow_version or 0) + 1
    tc.updated_at = datetime.now(timezone.utc)
    from app.services.ezs_site_work import log_event
    site = await db.get(EzsSite, tc.site_id)
    from app.services.ezs_changes import make_change
    await log_event(db, site, "edit", user=user, text="Обновлены условия, ответственность и контроль техприсоединения",
                    changes=[make_change("tc.workflow", {k: v for k, v in old.items() if not k.startswith("_")},
                                         w.model_dump(mode="json"), label="Условия и контроль ТП", category="decision")])
    await db.flush()
    return await read(db, tc)


async def deliver(db, tc):
    """Проверка на регламенте покрывает загрузки из проекта и общие файлы юрлица.

    None от штатной доставки (в том числе политика admin-only) не считается успехом.
    При повторе подтверждённое сообщение не дублируется.
    """
    from app.services.notify import notify_person, NOTICES_ROOM_KIND
    state = await read(db, tc)
    w = data_of(tc)
    delivered = dict((tc.workflow or {}).get("_delivery", {}))
    site = await db.get(EzsSite, tc.site_id)
    default = w.responsibilities.get("default", Responsibility())
    occasions = []
    if tc.method in ("direct", "indirect") and not state["missing"]:
        executor = w.responsibilities.get("applied", default).executor or default.executor
        if executor: occasions.append(("kit_ready", executor, ("Комплект ТП собран и проверен. Направьте заявку в сетевую организацию." if state["ready"] else "Документы ТП собраны. Проверьте содержание комплекта перед подачей заявки.")))
    else:
        # Новая готовность после изменения требований — новое уведомление.
        delivered = {k: v for k, v in delivered.items() if not k.startswith("kit_ready:")}
    if w.archived:
        controllers = {r.controller for r in w.responsibilities.values() if r.controller}
        for person in controllers: occasions.append(("archive", person, "Техприсоединение завершено. Итоговые документы закреплены в проекте."))
    for step in ezs_tp_steps.steps_out(tc):
        assignment = w.responsibilities.get(step["key"], default)
        due = assignment.due or (date.fromisoformat(step["plannedDate"]) if step["plannedDate"] else None)
        if due and due < date.today() and not step["date"]:
            for person in {assignment.executor or default.executor, assignment.controller or default.controller} - {None}:
                occasions.append((f"step:{step['key']}:{due}", person, f"Просрочен шаг: {step['label']} (срок {due})."))
    for stage in w.stages:
        if stage.due and stage.due < date.today() and not stage.done:
            for person in {stage.executor or default.executor, default.controller} - {None}:
                occasions.append((f"stage:{stage.id}:{stage.due}", person, f"Просрочен этап ТУ: {stage.title}."))
    for r in state["remarks"]:
        if r["overdue"]:
            for person in (default.executor, default.controller):
                if person: occasions.append((f"remark:{r['id']}:{r['deadline']}", person, f"Просрочен ответ на замечание: {r['text']}"))
    for key, person, message in occasions:
        delivery_key = f"{key}:{person}"
        if delivery_key in delivered: continue
        member = await db.get(UserCompany, (person, tc.company_id))
        target = await db.get(User, person)
        if not member or not target: continue
        if member.role != "admin" and member.object_scope and str(site.location_id) not in member.object_scope: continue
        if member.own_organization_id and member.own_organization_id != w.organization_id: continue
        msg = await notify_person(db, tc.company_id, target,
            f"{site.title or site.project_no or 'Проект'}: {message}\n"
            f"[Открыть присоединение](/projects?mode=projects&sub=pr_project&project={tc.site_id}&ptab=tp)",
            room_kind=NOTICES_ROOM_KIND, event_category="tech_connection")
        if msg: delivered[delivery_key] = {"messageId": str(msg), "at": datetime.now(timezone.utc).isoformat()}
    if delivered != (tc.workflow or {}).get("_delivery", {}):
        tc.workflow = dict(tc.workflow or {}, _delivery=delivered)


async def run_notifications(db, now):
    ids = (await db.execute(select(EzsTechConnection.id).where(EzsTechConnection.workflow.is_not(None)))).scalars().all()
    await db.commit()
    count = 0
    for ident in ids:
        tc = (await db.execute(select(EzsTechConnection).where(EzsTechConnection.id == ident)
                              .with_for_update(skip_locked=True))).scalar_one_or_none()
        if tc is None: continue
        try:
            await deliver(db, tc)
            from app.services.ezs_tp_method import reconcile
            await reconcile(db, tc)
            await db.commit()
            count += 1
        except Exception:
            await db.rollback()
            import logging
            logging.getLogger(__name__).exception("Не завершена проверка одного ТП; следующий проход повторит её")
    return count
