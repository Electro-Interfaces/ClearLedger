from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import uuid

from sqlalchemy import select

from app.models import Contract, Counterparty, EzsSiteDoc, MarketOperator, MarketSite, ServiceLocation, Task
from app.services.ezs_checklist_integration import TASKS, PHASES_DOC

SECTIONS = {
    "partner": ("name", "legalEntity", "purpose", "commercialContact", "assessment"),
    # Заявка — то, что известно на входе: кто инициатор, какой договор предполагается
    # (вид и кто кому платит — без ставок, это предмет переговоров), охват в общих чертах
    # и технический куратор (протоколы, техсогласование, доступы — не обязательно
    # руководитель проекта). Решение МАГа 05.10.2026: заявка не грузит протоколами.
    "lead": ("initiator", "contractKind", "payer", "coverage", "curatorUserId"),
    "commercial": ("commission", "calculationBase", "acquiring", "tariffs", "discounts",
                   "discountFunding", "settlements", "reporting"),
    "data": ("outgoing", "incoming", "statisticsUse", "sessionHistory", "analytics", "brand", "appTransitions"),
    "technical": ("systems", "protocol", "version", "contacts", "responsibilities", "support",
                  "access", "security", "acceptanceCriteria", "productionAccess"),
    # Порядок расчётов — общий для всех сценариев: когда, в какой срок, какими
    # документами и как разрешаются споры. Кто кому платит — в каждом сценарии.
    "settlement": ("period", "paymentTerm", "documents", "vat", "disputes", "minimums",
                   "penalties", "accountingChannel", "matchKind", "matchValues"),
    "work": ("pilotDecision", "pilotOutcome", "testResults", "launchDate"),
    "accounting": ("counterpartyId",),
}
RESULT_FIELDS = ("comment", "workRef", "docId", "notApplicable")
PAYERS = {"", "partner", "us", "none"}          # партнёр платит нам / мы партнёру / без расчётов
MODELS = {"", "commission", "fixed", "margin", "none"}
CONNECT_BASIS = {"check", "session"}            # проверено у принимающей стороны / прошла первая сессия
TEST_STATUSES = {"pending", "passed", "failed", "na"}
# Как сессия партнёра выглядит в нашем учёте. Партнёрский клиент заряжается под
# договорным аккаунтом юрлица (так сегодня приходят корпоративные клиенты: в сессии
# `card_owner_ext_id` и `client_name`, сумма — по тарифу клиента) или по выданным
# партнёру картам. Правило задаётся в паспорте и проверяется на живых сессиях.
LEAD_INITIATORS = {"", "partner", "us"}     # партнёр пришёл к нам / мы вышли на партнёра
LEAD_CONTRACT_KINDS = {"", "information", "roaming", "agency", "other"}
MATCH_KINDS = {"account": "Договорной аккаунт клиента", "client": "Юрлицо клиента в сессии", "card": "Номера карт"}
DOCUMENT_KINDS = {"nda", "pilot", "contract", "stations", "specification", "test_program", "test_protocol", "instruction", "other"}
SECTION_LABELS = {"lead": "заявка", "settlement": "порядок расчётов и учёт", "tests": "испытания", "reconciliations": "сверки", "listVersions": "версии перечней", "partner": "партнёр и цель", "commercial": "коммерческие условия", "data": "данные, аналитика и бренд", "technical": "технические параметры и сопровождение", "work": "пилот и проверки", "accounting": "связь с контрагентом", "scenarios": "сценарии и перечни ЭЗС", "documents": "редакции документов", "results": "результаты чек-листа", "dates": "план этапов", "contractIds": "договоры учёта"}


def read(site):
    stored = deepcopy((site.workspace_data or {}).get("integration") or {})
    for section in SECTIONS:
        stored.setdefault(section, {})
    for section in ("scenarios", "documents", "contractIds", "tests", "reconciliations", "listVersions"):
        stored.setdefault(section, [])
    for section in ("results", "dates"):
        stored.setdefault(section, {})
    stored.setdefault("revision", 0)
    return stored


def section_for(key):
    if key in {"1.3", "1.4.1"}:
        return "lead"
    if key in {"1.1", "1.5", "4.1"}:
        return "partner"
    if key in {"1.2", "1.6", "2.1", "5.3", "5.5", "6.7"}:
        return "scenarios"
    if key in {"2.2", "2.3", "6.1", "6.2", "6.3"}:
        return "commercial"
    if key in {"2.5", "2.6", "2.7", "3.2", "6.4"}:
        return "data"
    if key in {"2.8", "4.2", "6.12"}:
        return "work"
    if key in {"5.10", "5.11"}:
        return "tests"
    if key in {"5.12", "6.3"}:
        return "settlement"
    if key in {"5.13", "6.14"}:
        return "reconciliations"
    if key in {"4.3", "6.6"}:
        return "documents"
    return "technical"


# От чего ещё зависит подтверждение пункта, кроме своего раздела: изменились эти
# данные — подтверждение устарело. Условия сценария — без перечней станций:
# иначе каждая отметка станции сбрасывала бы согласование комиссии.
DEPENDS = {
    "2.2": ("terms", "settlement"), "2.3": ("terms",), "6.2": ("terms", "settlement"),
    "5.10": ("work",), "5.11": ("documents",), "6.6": ("listVersions",),
    "6.7": ("listVersions",),
}
TERM_FIELDS = ("payer", "model", "rate", "base", "clientPrice", "acquiring")


def _terms(data):
    return [{"id": s["id"], **{f: s.get(f, "") for f in ("direction", "format", *TERM_FIELDS)}} for s in data["scenarios"]]


def snapshot(site, key, data=None):
    data = data or read(site)
    section = section_for(key)
    values = {section: data.get(section), "result": data["results"].get(key)}
    for dep in DEPENDS.get(key, ()):
        values[dep] = _terms(data) if dep == "terms" else data.get(dep)
    if key == "1.4":
        values = {"owner": str(site.owner_user_id or ""), "result": data["results"].get(key)}
    if key == "2.8":
        values["dates"] = data["dates"]
    if key in {"5.10", "5.7", "5.8"}:
        values["work"] = data["work"]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def stale(site, key, mark):
    return bool(mark.get("needs_confirmation") or
                (mark.get("snapshot") and mark["snapshot"] != snapshot(site, key)))


# Расхождение сверки: сессии — штука в штуку, энергия и деньги — до округления
# (0,1 кВт·ч и 1 ₽). Больше — расхождение, его закрывает только урегулирование с
# актом: «примерно сошлось» сверкой не считается.
RECON_TOLERANCE = {"sessions": 0, "kwh": 0.1, "amount": 1.0}


def recon_state(r):
    diff = any(abs(float(r["ours"].get(k) or 0) - float(r["partner"].get(k) or 0)) > tol
               for k, tol in RECON_TOLERANCE.items())
    if not diff:
        return "match"
    return "resolved" if r.get("resolution") and r.get("docId") else "diff"


def match_values(settlement):
    """Значения правила: по одному на строку, через запятую или точку с запятой."""
    import re
    return sorted({v.strip() for v in re.split(r"[\n,;]+", settlement.get("matchValues") or "") if v.strip()})


async def partner_sessions(db, site, date_from, date_to):
    """Сессии партнёра в нашем учёте за период — по правилу из паспорта.

    Деньги — по тарифу клиента, где он есть (у корпоративного аккаунта `amount` = 0,
    расчёт идёт по договору), иначе списанное. Это та цифра, которую сверяют с
    отчётом партнёра.
    """
    from sqlalchemy import func, or_
    from app.models import ChargeSession as CS
    st = read(site)["settlement"]
    kind, values = st.get("matchKind"), match_values(st)
    if not kind or not values:
        raise ValueError("Правило выделения сессий партнёра не задано")
    column = {"account": [CS.card_owner_ext_id], "client": [CS.client_name], "card": [CS.card_number, CS.rfid]}[kind]
    match = or_(*[c.in_(values) for c in column])
    start = datetime.combine(date_from, datetime.min.time())
    end = datetime.combine(date_to, datetime.max.time())
    where = (CS.company_id == site.company_id, CS.started_at >= start, CS.started_at <= end, match)
    money = func.coalesce(CS.client_amount, CS.amount)
    month = func.to_char(CS.started_at, "YYYY-MM")
    rows = (await db.execute(select(month.label("m"), func.count().label("n"), func.coalesce(func.sum(CS.energy_kwh), 0).label("kwh"),
                                    func.coalesce(func.sum(money), 0).label("amount")).where(*where).group_by(month).order_by(month))).all()
    sample = (await db.execute(select(CS.started_at, CS.station_name, CS.client_name, CS.card_number, CS.energy_kwh, money.label("amount"))
                               .where(*where).order_by(CS.started_at.desc()).limit(5))).all()
    by_month = [{"month": r.m, "sessions": int(r.n), "kwh": round(float(r.kwh), 3), "amount": round(float(r.amount), 2)} for r in rows]
    return {
        "rule": {"kind": kind, "label": MATCH_KINDS[kind], "values": values},
        "from": date_from.isoformat(), "to": date_to.isoformat(),
        "total": {"sessions": sum(m["sessions"] for m in by_month), "kwh": round(sum(m["kwh"] for m in by_month), 3),
                  "amount": round(sum(m["amount"] for m in by_month), 2)},
        "byMonth": by_month,
        "sample": [{"at": r.started_at.isoformat() if r.started_at else None, "station": r.station_name, "client": r.client_name,
                    "card": r.card_number, "kwh": round(float(r.energy_kwh or 0), 3), "amount": round(float(r.amount or 0), 2)} for r in sample],
    }


def tests_state(data):
    """Испытания: все обязательные пройдены или неприменимы, проваленных нет."""
    tests = data["tests"]
    if not any(x["required"] for x in tests):
        return False, "Сформируйте испытания по сценариям и отметьте обязательные"
    open_ = [x["title"] for x in tests if x["required"] and x["status"] not in ("passed", "na")]
    if open_:
        return False, "Не пройдены обязательные испытания: " + "; ".join(open_[:3])
    return True, None


def versions_state(data):
    """Каждый согласованный перечень совпадает с последней версией, привязанной к подписанному документу."""
    docs = {d["id"]: d for d in data["documents"]}
    for s in data["scenarios"]:
        if not s["agreedIds"]:
            continue
        own = [v for v in data["listVersions"] if v["scenarioId"] == s["id"]]
        if not own:
            return False, f"Зафиксируйте версию перечня сценария «{s.get('name') or s['direction']}»"
        last = max(own, key=lambda v: v["version"])
        if set(last["stationIds"]) != set(s["agreedIds"]):
            return False, f"Согласованный перечень сценария «{s.get('name') or s['direction']}» изменён после версии {last['version']}"
        if not (docs.get(last["documentId"]) or {}).get("signedDocId"):
            return False, f"Версия {last['version']} перечня не привязана к подписанному документу"
    return True, None


def confirmation_problem(site, key, data):
    result = data["results"].get(key) or {}
    if result.get("notApplicable"):
        if key in {"4.3", "5.11", "6.6"}:
            return "Подписание обязательного документа нельзя заменить неприменимостью; решение об исключении оформляется снятием обязательности"
        return None if result.get("comment", "").strip() else "Укажите причину неприменимости"
    if not any(result.get(f) for f in ("comment", "workRef", "docId")):
        return "Запишите результат проверки, выберите документ или свяжите поручение"
    return requirement_problem(site, key, data)


def requirement_problem(site, key, data):
    """Чего не хватает в ДАННЫХ проекта, чтобы пункт можно было подтвердить.

    Отдельно от записи результата: карточка показывает это заранее — у пункта в чек-листе
    и в его окне. Раньше человек узнавал требование только из отказа при подтверждении
    (так 1.4 «руководитель не назначен» выглядел поломкой, замечание 05.10.2026).
    """
    p, t, w, c, st = (data[k] for k in ("partner", "technical", "work", "commercial", "settlement"))
    scenarios = data["scenarios"]
    terms_ok = bool(scenarios) and all(s.get("payer") and (s["payer"] == "none" or (s.get("model") and s.get("rate"))) for s in scenarios)
    tests_ok, tests_problem = tests_state(data)
    versions_ok, versions_problem = versions_state(data)
    required = {
        "1.1": (p.get("name") and p.get("purpose") and data["lead"].get("initiator"), "Заполните партнёра, цель и инициатора интеграции"),
        "1.3": (data["lead"].get("contractKind") and data["lead"].get("payer"), "Укажите вид предполагаемого договора и кто кому платит"),
        "1.4.1": (data["lead"].get("curatorUserId"), "Назначьте технического куратора интеграции"),
        "1.2": (bool(data["scenarios"]), "Добавьте сценарий подключения"),
        "1.4": (bool(site.owner_user_id), "Назначьте руководителя проекта в Работе"),
        "1.6": (any(s["selectedIds"] for s in data["scenarios"]), "Выберите станции сценария"),
        "2.2": (terms_ok and st.get("period"), "Укажите по каждому сценарию, кто кому платит, модель и ставку, и периодичность расчётов"),
        "2.3": (c.get("tariffs") or all(s.get("clientPrice") for s in scenarios if s["format"] == "roaming"), "Укажите цену для чужого клиента по сценариям роуминга или правила тарифов"),
        "2.4": (t.get("responsibilities") and t.get("support"), "Заполните ответственность и поддержку"),
        "2.8": (bool(data["dates"]), "Укажите плановые даты этапов"),
        "3.1": (t.get("protocol") and t.get("version"), "Укажите протокол и версию"),
        "3.6": (t.get("contacts"), "Укажите технические контакты сторон"),
        "4.1": (p.get("legalEntity"), "Укажите юридическое лицо партнёра"),
        "4.2": (w.get("pilotDecision"), "Зафиксируйте решение о пилоте"),
        "5.3": (any(s["pilotIds"] for s in data["scenarios"]), "Выберите пилотный перечень из станций сценария"),
        "5.10": (tests_ok and w.get("pilotOutcome"), tests_problem or "Зафиксируйте итог пилота"),
        "5.11": (tests_ok, tests_problem),
        "5.12": (st.get("matchKind") and match_values(st), "Задайте правило, по которому сессии партнёра находятся в учёте, и проверьте его на тестовой сессии"),
        "5.13": (any(r["kind"] == "pilot" and recon_state(r) != "diff" for r in data["reconciliations"]), "Внесите пробную сверку по пилоту: без расхождений или с урегулированием и актом"),
        "6.2": (terms_ok and all(st.get(f) for f in ("period", "paymentTerm", "documents", "vat")), "Заполните условия по сценариям и порядок расчётов: периодичность, срок оплаты, документы, НДС"),
        "6.3": (st.get("disputes"), "Опишите порядок сверки и разрешения расхождений"),
        "6.6": (versions_ok, versions_problem),
        "6.13": (t.get("productionAccess"), "Зафиксируйте выдачу боевых доступов и отзыв тестовых"),
        "6.14": (any(r["kind"] == "monthly" and recon_state(r) != "diff" and r.get("docId") for r in data["reconciliations"]), "Внесите месячную сверку без расхождений (или урегулированную) с подписанным актом"),
        "6.7": (bool(scenarios) and versions_ok and all(s["agreedIds"] and set(s["agreedIds"]) <= set(s["connectedIds"]) and all((s.get("connectedMeta") or {}).get(i, {}).get("at") for i in s["connectedIds"]) for s in scenarios), "Отметьте подключение всех станций согласованной версии перечня с датой и основанием"),
        "6.12": (w.get("launchDate"), "Зафиксируйте дату коммерческого запуска"),
    }
    if key in {"4.3", "5.11", "6.6"}:
        kinds = {"4.3": {"nda", "pilot"}, "5.11": {"test_protocol"}, "6.6": {"contract"}}[key]
        signed = [d for d in data["documents"] if d["kind"] in kinds and d.get("signedDocId") and d.get("signingEvidence")]
        if not signed:
            return "Выберите подписанную версию нужного документа и подтверждение подписания"
    if key in required and not required[key][0]:
        return required[key][1]
    return None


def normalize(payload, old):
    if not isinstance(payload, dict) or payload.get("revision") != old["revision"]:
        raise ValueError("Карточка изменилась. Обновите данные перед сохранением")
    data = deepcopy(old)
    if "contractIds" in payload:
        ids = payload["contractIds"]
        if not isinstance(ids, list) or len(ids) > 200 or any(not isinstance(i, str) for i in ids):
            raise ValueError("Некорректный перечень договоров")
        data["contractIds"] = sorted({str(uuid.UUID(i)) for i in ids})
    for section, fields in SECTIONS.items():
        if section in payload:
            source = payload[section]
            if not isinstance(source, dict):
                raise ValueError("Некорректный раздел паспорта")
            data[section] = {f: str(source.get(f) or "").strip()[:6000] for f in fields}
    if (data["settlement"].get("matchKind") or "") not in ("", *MATCH_KINDS):
        raise ValueError("Неизвестный способ выделения сессий партнёра")
    lead = data["lead"]
    if lead.get("initiator", "") not in LEAD_INITIATORS or lead.get("contractKind", "") not in LEAD_CONTRACT_KINDS \
            or lead.get("payer", "") not in PAYERS:
        raise ValueError("Неизвестное значение в заявке: инициатор, вид договора или плательщик")
    if lead.get("curatorUserId"):
        lead["curatorUserId"] = str(uuid.UUID(lead["curatorUserId"]))
    if "scenarios" in payload:
        source = payload["scenarios"]
        if not isinstance(source, list) or len(source) > 50:
            raise ValueError("Некорректный список сценариев")
        scenarios, seen = [], set()
        for s in source:
            sid = str(s.get("id") or uuid.uuid4())
            if sid in seen:
                raise ValueError("Идентификаторы сценариев повторяются")
            seen.add(sid)
            if s.get("direction") not in {"outgoing", "incoming"} or s.get("format") not in {"information", "roaming"}:
                raise ValueError("Сценарий должен иметь одно направление и один формат")
            row = {k: str(s.get(k) or "").strip()[:2000] for k in ("name", "geography", "restrictions", "partnerNetwork")}
            row.update(id=sid, direction=s["direction"], format=s["format"])
            for field in ("selectedIds", "agreedIds", "connectedIds", "pilotIds"):
                ids = s.get(field) or []
                if not isinstance(ids, list) or len(ids) > 20000 or any(not isinstance(i, str) for i in ids):
                    raise ValueError("Некорректный перечень станций")
                row[field] = sorted(set(ids))
            if not set(row["agreedIds"]) <= set(row["selectedIds"]):
                raise ValueError("Согласованный перечень должен входить в выбранный")
            if not set(row["connectedIds"]) <= set(row["agreedIds"]):
                raise ValueError("Подключённые станции должны входить в согласованный перечень")
            if not set(row["pilotIds"]) <= set(row["selectedIds"]):
                raise ValueError("Пилотные станции должны входить в сценарий")
            # Кто кому платит — в каждом сценарии свой ответ: в двустороннем
            # роуминге деньги идут в обе стороны и по разным правилам.
            if (s.get("payer") or "") not in PAYERS or (s.get("model") or "") not in MODELS:
                raise ValueError("Неизвестный плательщик или модель расчётов")
            row.update({f: str(s.get(f) or "").strip()[:500] for f in TERM_FIELDS})
            meta = s.get("connectedMeta") or {}
            if not isinstance(meta, dict) or not set(meta) <= set(row["connectedIds"]):
                raise ValueError("Дата подключения указана для станции вне подключённого перечня")
            row["connectedMeta"] = {}
            for sid, m in meta.items():
                at, basis = str(m.get("at") or ""), str(m.get("basis") or "")
                if at:
                    date.fromisoformat(at)
                if basis not in CONNECT_BASIS:
                    raise ValueError("Укажите основание подключения: проверка у принимающей стороны или первая сессия")
                row["connectedMeta"][sid] = {"at": at, "basis": basis, "ref": str(m.get("ref") or "").strip()[:300]}
            scenarios.append(row)
        data["scenarios"] = scenarios
    if "documents" in payload:
        if not isinstance(payload["documents"], list) or len(payload["documents"]) > 200:
            raise ValueError("Некорректный перечень документов")
        documents, seen = [], set()
        for d in payload["documents"]:
            if d.get("kind") not in DOCUMENT_KINDS:
                raise ValueError("Неизвестный вид документа интеграции")
            row = {k: str(d.get(k) or "").strip()[:2000] for k in ("id", "kind", "title", "edition", "fileDocId", "agreedDocId", "signedDocId", "signingEvidence")}
            row["id"] = row["id"] or str(uuid.uuid4())
            if row["id"] in seen:
                raise ValueError("Идентификаторы документов повторяются")
            seen.add(row["id"])
            if row["signedDocId"] and not row["signingEvidence"]:
                raise ValueError("Укажите подтверждение подписания документа")
            documents.append(row)
        data["documents"] = documents
    if "tests" in payload:
        source = payload["tests"]
        if not isinstance(source, list) or len(source) > 300:
            raise ValueError("Некорректный перечень испытаний")
        known = {s["id"] for s in data["scenarios"]}
        tests, seen = [], set()
        for x in source:
            row = {k: str(x.get(k) or "").strip()[:2000] for k in ("id", "scenarioId", "title", "sessionRef", "comment", "docId")}
            row["id"] = row["id"] or str(uuid.uuid4())
            if row["id"] in seen or not row["title"]:
                raise ValueError("У испытания должно быть название")
            seen.add(row["id"])
            if row["scenarioId"] not in known:
                row["scenarioId"] = ""  # сценарий удалён — испытание остаётся общим
            row["status"] = str(x.get("status") or "pending")
            if row["status"] not in TEST_STATUSES:
                raise ValueError("Неизвестный статус испытания")
            if row["status"] in ("failed", "na") and not row["comment"]:
                raise ValueError(f"Испытание «{row['title']}»: опишите замечание или причину неприменимости")
            row["required"] = bool(x.get("required"))
            tests.append(row)
        data["tests"] = tests
    if "reconciliations" in payload:
        source = payload["reconciliations"]
        if not isinstance(source, list) or len(source) > 120:
            raise ValueError("Некорректный перечень сверок")
        recs, seen = [], set()
        for r in source:
            row = {k: str(r.get(k) or "").strip()[:2000] for k in ("id", "period", "resolution", "docId")}
            row["id"] = row["id"] or str(uuid.uuid4())
            if row["id"] in seen:
                raise ValueError("Идентификаторы сверок повторяются")
            seen.add(row["id"])
            for f in ("from", "to"):
                row[f] = str(r.get(f) or "")
                if row[f]:
                    date.fromisoformat(row[f])
            if row["from"] and row["to"] and row["from"] > row["to"]:
                raise ValueError("Конец периода сверки раньше начала")
            row["kind"] = str(r.get("kind") or "")
            if row["kind"] not in ("pilot", "monthly") or not row["period"]:
                raise ValueError("Укажите вид сверки и период")
            for side in ("ours", "partner"):
                values = r.get(side) or {}
                try:
                    row[side] = {k: max(0.0, float(values.get(k) or 0)) for k in RECON_TOLERANCE}
                except (TypeError, ValueError):
                    raise ValueError("Сессии, кВт·ч и суммы сверки должны быть числами")
            recs.append(row)
        data["reconciliations"] = recs
    if "listVersions" in payload:
        source = payload["listVersions"]
        if not isinstance(source, list):
            raise ValueError("Некорректные версии перечней")
        old_versions = {v["id"]: v for v in old["listVersions"]}
        # Версия перечня — то, что подписали: прежние версии не правятся и не
        # удаляются, новая — только снимок текущего согласованного перечня.
        if not set(old_versions) <= {str(v.get("id")) for v in source}:
            raise ValueError("Зафиксированную версию перечня удалить нельзя")
        versions = []
        for v in source:
            vid = str(v.get("id") or "")
            if vid in old_versions:
                versions.append(old_versions[vid])
                continue
            scenario = next((s for s in data["scenarios"] if s["id"] == v.get("scenarioId")), None)
            if scenario is None or not scenario["agreedIds"]:
                raise ValueError("Версию можно зафиксировать только для сценария с согласованным перечнем")
            if not any(d["id"] == v.get("documentId") for d in data["documents"]):
                raise ValueError("Выберите документ, к которому относится версия перечня")
            number = 1 + max([x["version"] for x in versions + list(old_versions.values()) if x["scenarioId"] == scenario["id"]], default=0)
            versions.append({"id": vid or str(uuid.uuid4()), "scenarioId": scenario["id"], "version": number,
                             "stationIds": sorted(scenario["agreedIds"]), "documentId": str(v["documentId"]),
                             "note": str(v.get("note") or "").strip()[:1000], "new": True})
        data["listVersions"] = versions
    if "results" in payload:
        keys = {t["key"] for t in TASKS}
        if not isinstance(payload["results"], dict) or not set(payload["results"]) <= keys:
            raise ValueError("Неизвестный пункт чек-листа")
        data["results"] = {k: {f: bool(v.get(f)) if f == "notApplicable" else str(v.get(f) or "").strip()[:6000]
                               for f in RESULT_FIELDS} for k, v in payload["results"].items()}
    if "dates" in payload:
        dates = {}
        if not isinstance(payload["dates"], dict) or not set(payload["dates"]) <= {p["code"] for p in PHASES_DOC}:
            raise ValueError("Неизвестный этап")
        for key, values in payload["dates"].items():
            row = {}
            for f in ("start", "end"):
                value = str(values.get(f) or "")
                if value:
                    date.fromisoformat(value)
                row[f] = value
            if row["start"] and row["end"] and row["start"] > row["end"]:
                raise ValueError("Окончание этапа раньше начала")
            if row["start"] or row["end"]:
                dates[key] = row
        data["dates"] = dates
    if data["work"].get("launchDate"):
        date.fromisoformat(data["work"]["launchDate"])
    return data


async def validate_refs(db, site, data):
    for direction, model in (("outgoing", ServiceLocation), ("incoming", MarketSite)):
        ids = {i for s in data["scenarios"] if s["direction"] == direction for i in s["selectedIds"]}
        if ids:
            values = [uuid.UUID(i) for i in ids] if model == MarketSite else list(ids)
            stmt = select(model.id).where(model.company_id == site.company_id, model.id.in_(values))
            stmt = stmt.where(ServiceLocation.type == "ev_charging", ServiceLocation.is_test.is_(False)) if model == ServiceLocation else stmt.where(MarketSite.location_id.is_(None), MarketSite.kind == "ezs", MarketSite.duplicate_of_id.is_(None))
            found = {str(i) for i in (await db.execute(stmt)).scalars()}
            if ids - found:
                raise ValueError("Перечень содержит станции вне выбранной сети или пространства")
    doc_ids = {d[f] for d in data["documents"] for f in ("fileDocId", "agreedDocId", "signedDocId") if d.get(f)}
    doc_ids.update(r["docId"] for r in data["results"].values() if r.get("docId"))
    doc_ids.update(r["docId"] for r in data["tests"] + data["reconciliations"] if r.get("docId"))
    if doc_ids:
        found = {str(i) for i in (await db.execute(select(EzsSiteDoc.id).where(
            EzsSiteDoc.company_id == site.company_id, EzsSiteDoc.site_id == site.id,
            EzsSiteDoc.file_id.is_not(None), EzsSiteDoc.id.in_([uuid.UUID(i) for i in doc_ids])))).scalars()}
        if doc_ids - found:
            raise ValueError("Документ не приложен к этому проекту или не содержит файла")
    for result in data["results"].values():
        ref = result.get("workRef")
        if ref:
            kind, sep, ident = ref.partition(":")
            if kind != "task" or not sep:
                raise ValueError("Выберите поручение Трека")
            task = (await db.execute(select(Task.id).where(Task.company_id == site.company_id, Task.id == uuid.UUID(ident)))).scalar_one_or_none()
            if task is None:
                raise ValueError("Поручение не относится к пространству")
    cp = data["accounting"].get("counterpartyId")
    if cp and (await db.execute(select(Counterparty.id).where(Counterparty.company_id == site.company_id, Counterparty.id == uuid.UUID(cp)))).scalar_one_or_none() is None:
        raise ValueError("Контрагент не относится к пространству")
    ids = set(data.get("contractIds") or [])
    if ids:
        found = {str(i) for i in (await db.execute(select(Contract.id).where(
            Contract.company_id == site.company_id, Contract.id.in_([uuid.UUID(i) for i in ids])))).scalars()}
        if ids - found:
            raise ValueError("Договор не относится к пространству")


def stamp(old, data, user):
    """Автор и дата у испытаний, сверок и версий перечня ставит сервер, а не клиент.

    Испытание и сверка подписываются тем, кто изменил их содержание; не тронутые
    строки сохраняют прежнего автора — иначе любое сохранение перечня переписало
    бы, кто и когда провёл испытание.
    """
    now = datetime.now(timezone.utc).isoformat()
    who = {"by": str(user.id), "byName": getattr(user, "name", None) or getattr(user, "email", ""), "at": now}
    authored = ("by", "byName", "at")
    for key, fields in (("tests", ("status", "sessionRef", "comment", "docId", "required", "title")),
                        ("reconciliations", ("period", "kind", "ours", "partner", "resolution", "docId"))):
        before = {x["id"]: x for x in old[key]}
        for row in data[key]:
            prev = before.get(row["id"])
            if prev and all(prev.get(f) == row.get(f) for f in fields):
                row.update({f: prev.get(f) for f in authored})
            else:
                row.update(who)
    for v in data["listVersions"]:
        if v.pop("new", False):
            v.update(who)


async def save(db, site, payload, user):
    from app.services.ezs_site_work import log_event
    old = read(site)
    data = normalize(payload, old)
    await validate_refs(db, site, data)
    stamp(old, data, user)
    changed = [k for k in data if k != "revision" and data[k] != old.get(k)]
    if not changed:
        return old
    gates = deepcopy(site.gates or {})
    invalidated = []
    for task in TASKS:
        mark = (gates.get(task["stage"]) or {}).get(task["key"]) or {}
        if (mark.get("done") or mark.get("waived")) and snapshot(site, task["key"], old) != snapshot(site, task["key"], data):
            mark["needs_confirmation"] = True
            gates[task["stage"]][task["key"]] = mark
            invalidated.append(task["key"])
    data["revision"] += 1
    site.workspace_data = {**(site.workspace_data or {}), "integration": data}
    site.gates = gates
    site.updated_at = site.last_touch_at = datetime.now(timezone.utc)
    await log_event(db, site, "edit", user=user, text="Интеграция: обновлены " + ", ".join(SECTION_LABELS[k] for k in changed),
                    changes=[{"field": f"integration:{k}", "label": f"Интеграция: {SECTION_LABELS[k]}", "category": "decision", "old": old[k], "new": data[k]} for k in changed])
    if invalidated:
        await log_event(db, site, "gate", user=user, text="Требуют повторного подтверждения: " + ", ".join(invalidated))
    return data


async def confirm(db, site, key, revision, user):
    from app.services.ezs_site_work import log_event
    data = read(site)
    task = next((t for t in TASKS if t["key"] == key), None)
    if task is None:
        raise ValueError("Неизвестный пункт чек-листа")
    if data["revision"] != revision:
        raise ValueError("Карточка изменилась. Обновите данные перед подтверждением")
    problem = confirmation_problem(site, key, data)
    if problem:
        raise ValueError(problem)
    await validate_refs(db, site, data)
    gates = deepcopy(site.gates or {})
    marks = gates.setdefault(task["stage"], {})
    now = datetime.now(timezone.utc).isoformat()
    marks[key] = {**(marks.get(key) or {}), "done": True, "waived": False,
                  "needs_confirmation": False, "snapshot": snapshot(site, key, data),
                  "by": str(user.id), "by_name": user.name or user.email, "at": now}
    site.gates = gates
    data["revision"] += 1
    site.workspace_data = {**(site.workspace_data or {}), "integration": data}
    site.last_touch_at = datetime.now(timezone.utc)
    await log_event(db, site, "gate", user=user, text=f"Подтверждён пункт {key}: {task['label']}",
                    changes=[{"field": f"integration:confirmation:{key}", "label": task["label"], "category": "decision", "old": None, "new": {"result": data["results"].get(key), "by": str(user.id), "at": now, "snapshot": marks[key]["snapshot"]}}])
    return data


async def station_catalog(db, company_id):
    own = (await db.execute(select(ServiceLocation).where(ServiceLocation.company_id == company_id,
        ServiceLocation.type == "ev_charging", ServiceLocation.is_test.is_(False)))).scalars().all()
    partner = (await db.execute(select(MarketSite, MarketOperator.name).outerjoin(
        MarketOperator, MarketOperator.id == MarketSite.operator_id).where(MarketSite.company_id == company_id,
        MarketSite.location_id.is_(None), MarketSite.kind == "ezs", MarketSite.duplicate_of_id.is_(None)))).all()
    rows = []
    for s in own:
        meta = s.extra_metadata or {}
        rows.append({"id": str(s.id), "network": "outgoing", "code": s.code, "name": s.name,
            "region": meta.get("federalSubject"), "city": s.city, "address": s.address,
            "sessions": 0, "speed": s.speed_class, "placement": s.location_class,
            "brand": s.brand, "power": s.power_kwt, "ports": s.connectors_count,
            "connectors": (s.connector_types or "").split(","), "opStatus": s.operational_status,
            "owner": s.owner, "protocol": s.ocpp_protocol, "model": s.model,
            "access": s.access_type, "lifecycle": s.status, "corp": False,
            "group": str(meta.get("stationGroup") or meta.get("group") or "")})
    for s, operator_name in partner:
        rows.append({"id": str(s.id), "network": "incoming", "code": str(s.id), "name": s.name,
            "region": s.region, "city": s.city, "address": s.address, "sessions": 0,
            "speed": None, "placement": None, "brand": s.vendor, "power": float(s.max_power_kw) if s.max_power_kw else None,
            "ports": s.ports, "connectors": (s.connectors or "").split(","), "opStatus": None,
            "owner": operator_name, "protocol": None, "model": None,
            "access": None, "lifecycle": None, "corp": False, "group": operator_name or ""})
    return rows

# Раздел «Интеграции»: реестр и отчёт. Интеграция живёт в той же таблице проектов,
# но читается своими вопросами — с кем, в каком формате, сколько станций передано и
# подключено, где подтверждения устарели. Стройка этих проектов в своих сводках не
# видит (`ezs_sites.not_integration`).
def portfolio_row(site, owner_name=None, today=None):
    from app.services.ezs_checklist_integration import STAGE_LABELS as labels
    from app.services.ezs_sites import STAGE_LABELS as common
    from app.services.ezs_site_work import GATES_BY_KIND
    data = read(site)
    today = today or date.today().isoformat()
    scenarios = [{"direction": s["direction"], "format": s["format"], "name": s.get("name") or "",
                  **{k: len(s.get(f) or []) for k, f in (("selected", "selectedIds"), ("agreed", "agreedIds"),
                                                         ("connected", "connectedIds"), ("pilot", "pilotIds"))}}
                 for s in data["scenarios"]]
    gates = site.gates or {}
    required = done = stale_n = 0
    for stage, items in GATES_BY_KIND["integration"].items():
        for it in items:
            mark = (gates.get(stage) or {}).get(it["key"]) or {}
            outdated = stale(site, it["key"], mark)
            stale_n += outdated
            if it.get("required"):
                required += 1
                done += bool(mark.get("done") or mark.get("waived")) and not outdated
    due = site.next_action_due or None
    return {
        "id": str(site.id), "projectNo": site.project_no, "title": site.title,
        "stage": site.stage, "stageLabel": labels.get(site.stage) or common.get(site.stage, site.stage),
        "owner": owner_name, "nextAction": site.next_action, "nextActionDue": due,
        "overdue": bool(due and due < today and site.stage not in ("archive", "live")),
        "partner": data["partner"].get("name") or "", "legalEntity": data["partner"].get("legalEntity") or "",
        "formats": sorted({s["format"] for s in scenarios}), "directions": sorted({s["direction"] for s in scenarios}),
        "scenarios": scenarios,
        "stations": {k: sum(s[k] for s in scenarios) for k in ("selected", "agreed", "connected", "pilot")},
        "pilotDecision": data["work"].get("pilotDecision") or "", "pilotOutcome": data["work"].get("pilotOutcome") or "",
        "launchDate": data["work"].get("launchDate") or "",
        "checklist": {"required": required, "closed": done, "stale": stale_n},
        "tests": {"total": len(data["tests"]), "required": sum(x["required"] for x in data["tests"]),
                  "passed": sum(x["status"] == "passed" for x in data["tests"]),
                  "failed": sum(x["status"] == "failed" for x in data["tests"])},
        "reconciliation": (lambda r: r and {"kind": r["kind"], "period": r["period"], "state": recon_state(r)})(
            data["reconciliations"][-1] if data["reconciliations"] else None),
        "launchOpen": site.stage == "live" and done < required,
        "updatedAt": site.last_touch_at.isoformat() if site.last_touch_at else None,
    }


def summarize(rows):
    """Сводка отчёта по строкам реестра — чистая функция, проверяется без БД."""
    active = [r for r in rows if r["stage"] not in ("archive", "live")]
    by = lambda key: {v: sum(1 for r in rows for x in [r[key]] if x == v) for v in sorted({r[key] for r in rows})}
    stations = {}
    for r in rows:
        for s in r["scenarios"]:
            cell = stations.setdefault(f'{s["direction"]}:{s["format"]}', {"selected": 0, "agreed": 0, "connected": 0, "pilot": 0, "projects": 0})
            for k in ("selected", "agreed", "connected", "pilot"):
                cell[k] += s[k]
            cell["projects"] += 1
    partners = {}
    for r in rows:
        name = r["partner"] or r["title"] or "—"
        p = partners.setdefault(name, {"partner": name, "projects": 0, "selected": 0, "agreed": 0, "connected": 0, "stages": []})
        p["projects"] += 1
        for k in ("selected", "agreed", "connected"):
            p[k] += r["stations"][k]
        p["stages"].append(r["stageLabel"])
    return {
        "total": len(rows), "active": len(active), "live": sum(r["stage"] == "live" for r in rows),
        "onHold": sum(r["stage"] == "on_hold" for r in rows), "archived": sum(r["stage"] == "archive" for r in rows),
        "byStage": by("stageLabel"),
        "stations": stations,
        "partners": sorted(partners.values(), key=lambda p: (-p["connected"], -p["agreed"], p["partner"])),
        "attention": {
            "stale": [r["id"] for r in rows if r["checklist"]["stale"]],
            "overdue": [r["id"] for r in active if r["overdue"]],
            "noOwner": [r["id"] for r in active if not r["owner"]],
            "noScenario": [r["id"] for r in active if not r["scenarios"]],
            "testsFailed": [r["id"] for r in rows if r["tests"]["failed"]],
            "reconDiff": [r["id"] for r in rows if (r["reconciliation"] or {}).get("state") == "diff"],
            "launchOpen": [r["id"] for r in rows if r["launchOpen"]],
        },
        "pilots": [{"id": r["id"], "title": r["title"], "partner": r["partner"], "decision": r["pilotDecision"],
                    "outcome": r["pilotOutcome"]} for r in rows if r["pilotDecision"] or r["pilotOutcome"]],
    }


async def portfolio(db, company_id):
    from app.models import EzsSite, User
    res = (await db.execute(select(EzsSite, User.name).outerjoin(User, User.id == EzsSite.owner_user_id).where(
        EzsSite.company_id == company_id, EzsSite.kind == "integration").order_by(EzsSite.last_touch_at.desc().nullslast()))).all()
    rows = [portfolio_row(s, owner) for s, owner in res]
    return {"items": rows, "summary": summarize(rows)}
