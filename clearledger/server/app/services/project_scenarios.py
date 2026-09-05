from fastapi import HTTPException


SCENARIOS = {
    "procurement": {
        "name": "Закупка", "fields": {"need": "Что и сколько закупить", "supplier": "Поставщик", "budget": "Бюджет, ₽"},
        "steps": [
            {"code": "need", "name": "Потребность", "result": "Потребность и бюджет подтверждены", "requirement": "done", "fields": ["need", "budget"]},
            {"code": "approval", "name": "Согласование", "result": "Закупка согласована", "requirement": "approved"},
            {"code": "order", "name": "Заказ", "result": "Заказ подтверждён поставщиком", "requirement": "approved", "fields": ["supplier"]},
            {"code": "delivery", "name": "Поставка", "result": "Поставка проверена", "requirement": "done"},
            {"code": "acceptance", "name": "Приёмка", "result": "Приёмочный документ подписан", "requirement": "signed"},
        ],
    },
    "warehouse": {
        "name": "Склад", "fields": {"need": "Номенклатура и количество", "warehouse": "Склад", "recipient": "Получатель"},
        "steps": [
            {"code": "reserve", "name": "Потребность / резерв", "result": "Резерв подтверждён в складском учёте", "requirement": "done", "fields": ["need", "warehouse"]},
            {"code": "supply", "name": "Обеспечение", "result": "Комплектация проверена", "requirement": "done"},
            {"code": "transfer", "name": "Выдача / передача", "result": "Передача подтверждена подписанным документом", "requirement": "signed", "fields": ["recipient"]},
        ],
    },
    "corporate_client": {
        "name": "Корпоративный клиент", "fields": {"client": "Клиент", "request": "Запрос клиента", "commitments": "Обязательства и объём"},
        "steps": [
            {"code": "request", "name": "Обращение", "result": "Запрос уточнён", "requirement": "done", "fields": ["client", "request"]},
            {"code": "proposal", "name": "Предложение", "result": "Предложение согласовано", "requirement": "approved"},
            {"code": "contract", "name": "Договорённости", "result": "Договор подписан", "requirement": "signed", "fields": ["commitments"]},
            {"code": "execution", "name": "Исполнение", "result": "Обязательства выполнены", "requirement": "done"},
            {"code": "result", "name": "Результат", "result": "Результат принят клиентом", "requirement": "signed"},
        ],
    },
}


def scenario(site):
    spec = SCENARIOS.get(site.kind)
    if spec is None:
        return None
    data = (site.workspace_data or {}).get("scenario", {})
    return {**spec, "stage": data.get("stage", spec["steps"][0]["code"]),
            "values": data.get("fields", {}), "templates": data.get("templates", {}), "evidence": data.get("evidence", {})}


def validate_fields(spec, values):
    if set(values) - set(spec["fields"]):
        raise HTTPException(400, "Неизвестное поле сценария")
    for key, value in values.items():
        if not isinstance(value, str) or len(value) > 2000:
            raise HTTPException(400, "Поле должно содержать не более 2000 символов")
        if key == "budget" and value:
            try:
                import math
                amount = float(value.replace(",", "."))
                valid = math.isfinite(amount) and amount >= 0
            except ValueError:
                valid = False
            if not valid:
                raise HTTPException(400, "Укажите неотрицательный бюджет числом")


def evidence_satisfies(kind, row, requirement, *, signed=False):
    if kind == "task":
        return requirement == "done" and row.status == "done"
    if row.status in ("cancelled", "archived"):
        return False
    if requirement == "signed":
        return signed and row.approval_status != "pending"
    return row.approval_status == "approved" if requirement == "approved" else row.status == "executed"
