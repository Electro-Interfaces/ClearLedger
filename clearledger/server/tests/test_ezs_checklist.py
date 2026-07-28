"""Чек-лист согласования ЗУ и разбор 55 граф банка данных.

Ловим две тихие поломки:
  • пункт чек-листа ссылается на несуществующее поле — гейт никогда не
    закроется, и никто не поймёт почему (ошибки нет, просто «не сделано»);
  • графа файла перестала распознаваться — значение уедет в `raw` и пропадёт
    из расчётов, как это было со стоимостью техприса до 28.07.2026.
"""
from app.models import EzsSite, EzsTechConnection
from app.services.ezs_checklist import TASKS, checklist_meta, gates_by_stage
from app.services.ezs_sites import (
    ALL_STAGES, _bool, _match_field, _num, _tc_values,
    format_project_no, parse_project_seq, project_no_prefix,
)

# Заголовки листа «Банк данных ЗУ сводный» — все 55 обязательных граф.
BANK_HEADERS = [
    "Дата поступления", "Статус", "Регион", "Город", "Адрес", "Полный адрес",
    "Признак (город/трасса)", "Место установки", "Трасса", "Координаты",
    "Ссылка на карту", "Собственник", "Бренд", "Площадь ЗУ, м2",
    "Статус ЗУ (собственность/аренда/муницип.)", "Комментарий",
    "Свободная мощность, кВт", "Входная стоимость, руб./кВт*ч.",
    "Стоимость техприса, руб. с НДС", "Стоимость СМР, руб. с НДС",
    "Итого затраты на подключение (техприс), руб. с НДС", "Расстояние до ТП, м",
    "Реконструкция ТП (да/нет)", "Стоимость аренды, руб./мес.",
    "Долгосрочный договор (да/нет)", "Видеонаблюдение (да/нет)",
    "Свободный доступ (да/нет)", "Сотовая связь (да/нет)",
    "Контакт представителя собственника", "Контакт предоставившего ЗУ - компания",
    "Контакт предоставившего ЗУ - ФИО", "Мощность ЭЗС к установке, кВт", "Кол-во ЭЗС",
    "Порты ЭЗС - GBT", "Порты ЭЗС - CCS", "Порты ЭЗС - Chademo", "Порты ЭЗС - Type",
    "Поставщик", "Подрядчик (наименование, ОПФ)", "Причина согласия / отказа",
    "Статус согласования / ТУ (заметки)", "Тип технологического присоединения АЗС",
    "Принадлежность подстанции", "Принадлежность КЛ/ВЛ 6-10 кВ",
    "Мощность силового трансформатора, кВт", "Тип и сечение КЛ/ВЛ 6-10 кВ",
    "Возможность доп. мощности КЛ/ВЛ >=150 кВт (да/нет)",
    "Возможность замены трансформатора без замены подстанции (да/нет)",
    "Ориент. стоимость договора с электросетевой организацией, руб. с НДС",
    "Ориент. стоимость мероприятий Общества по ТУ (ПИР и СМР), руб. с НДС",
    "Итого затраты на подключение (ТУ), руб. с НДС",
    "Сроки мероприятий электросетевой организации, мес.",
    "Сроки мероприятий Заявителя, мес.",
    "Доп.сервис (магазин, кафе/кофе-корнер, WC, мойка, подкачка шин)",
    "Требует проверки (авто)",
]

# Служебные ключи, у которых нет своего поля в `ezs_sites`: они едут в карточку
# присоединения (`_TC_FROM_IMPORT`) или используются только при разборе.
NOT_SITE_FIELDS = {
    "tp_reconstruction", "substation_owner", "line_owner", "transformer_kva",
    "line_type", "extra_power_possible", "transformer_swap_possible",
    "tu_contract_cost", "tu_works_cost", "tu_total_cost", "applicant_term_months",
}


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def test_все_графы_банка_распознаются():
    unmatched = [h for h in BANK_HEADERS if _match_field(_norm(h)) is None]
    # «Требует проверки (авто)» — служебная пометка прошлых чисток, своего поля
    # не имеет и остаётся только в raw.
    assert unmatched == ["Требует проверки (авто)"], unmatched


def test_итого_затраты_ту_не_путается_с_техприсом():
    assert _match_field(_norm("Итого затраты на подключение (ТУ), руб. с НДС")) == "tu_total_cost"
    assert _match_field(_norm(
        "Итого затраты на подключение (техприс), руб. с НДС")) == "connection_cost"


def test_поля_чек_листа_существуют_в_модели():
    cols = set(EzsSite.__table__.columns.keys()) | {"address_any"}
    for t in TASKS:
        fields = t.get("fields") or ([t["field"]] if t.get("field") else [])
        for f in fields:
            assert f in cols, f"пункт {t['key']}: поля {f} нет в ezs_sites"


def test_каждая_задача_знает_как_закрывается():
    for t in TASKS:
        ways = [k for k in ("field", "fields", "doc", "equipment", "manual") if t.get(k)]
        assert len(ways) == 1, f"пункт {t['key']}: способов проверки {ways}"
        assert t["stage"] in ALL_STAGES, f"пункт {t['key']}: стадия {t['stage']} неизвестна"
        assert t["role"], f"пункт {t['key']}: нет ответственного"


def test_гейты_собираются_по_стадиям():
    gates = gates_by_stage()
    assert sum(len(v) for v in gates.values()) == len(TASKS)
    # Ключи пунктов уникальны внутри стадии: отметка «сделано» кладётся по ключу.
    for stage, items in gates.items():
        keys = [i["key"] for i in items]
        assert len(keys) == len(set(keys)), stage
    meta = checklist_meta()
    assert sum(len(p["tasks"]) for p in meta["phases"]) == len(TASKS)


def test_карточка_тп_из_файла_режется_по_длине_колонки():
    # В графе про трансформатор пишут абзац — вставка падала на varchar(80).
    long_text = "две подстанции по 63 кВА, " * 20
    vals = {"transformer_kva": long_text, "line_type": long_text,
            "substation_owner": long_text, "tp_reconstruction": "нет",
            "tu_contract_cost": "43837.22", "applicant_term_months": "24"}
    tc = _tc_values(vals)
    for field, v in tc.items():
        limit = getattr(EzsTechConnection.__table__.c[field].type, "length", None)
        if limit and isinstance(v, str):
            assert len(v) <= limit, field
    assert tc["needs_reconstruction"] is False
    assert tc["cost"] == 43837.22
    assert tc["applicant_term_months"] == 24


def test_номер_проекта_счётчиком():
    # Импорт раздаёт номера из одного максимума: формат обязан совпадать с тем,
    # что выдаёт ручное создание, иначе следующий максимум не распознается.
    prefix = project_no_prefix()
    assert prefix.startswith("ЭЗС-") and prefix.endswith("-")
    assert format_project_no(prefix, 42).endswith("-0042")
    assert parse_project_seq(format_project_no(prefix, 42)) == 42
    assert parse_project_seq(None) == 0
    assert parse_project_seq("мусор") == 0


def test_разбор_значений_из_файла():
    assert _num("100кВт") == 100
    assert _num("800 т.р.") == 800000        # тысячи рублей → рубли
    assert _num("60-80") == 60               # диапазон → нижняя граница
    assert _num("43837.22") == 43837.22
    assert _bool("да") is True
    assert _bool("Нет") is False
    assert _bool("есть") is True
    # «для электромобилей» — не «нет»: это невыясненное значение.
    assert _bool("для электромобилей") is None
    assert _bool("?") is None


def test_типы_проектов_согласованы():
    from app.services.ezs_lifecycle import (
        CLOSE_MODES, KIND_LABELS, KIND_START_STAGE, PROJECT_KINDS,
    )
    # Возврат из эксплуатации начинается с решения, а не с подбора площадки:
    # место уже выбрано в прошлой жизни объекта.
    for k in PROJECT_KINDS:
        assert k["startStage"] in ALL_STAGES, k["key"]
        assert KIND_LABELS[k["key"]] == k["label"]
    assert KIND_START_STAGE["new_build"] == "lead"
    for kind in ("retrofit", "relocation", "decommission"):
        assert KIND_START_STAGE[kind] == "decision", kind
    # Приостановка и отмена — разные режимы: у них разные последствия для счёта 08.
    assert {m["key"] for m in CLOSE_MODES} == {"on_hold", "archive"}


def test_срок_мероприятий_зеркалится_из_присоединения():
    """Пункт 5.6 ждёт срок в графе площадки, а вводят его во вкладке «Присоединение».

    Считаем месяцы так же, как это делает `upsert_tech_connection`: без зеркала
    человек заполняет присоединение целиком, а чек-лист требует «зафиксировать срок».
    """
    from datetime import date as _d

    def months(app_date: str, due: str) -> float | None:
        days = (_d.fromisoformat(due) - _d.fromisoformat(app_date)).days
        return round(days / 30.44, 1) if days > 0 else None

    assert months("2026-07-10", "2026-11-30") == 4.7   # 143 дня ≈ 4,7 месяца
    assert months("2026-11-30", "2026-07-10") is None      # срок раньше заявки — не срок
    # Пункт 5.6 действительно смотрит в графу площадки, а не в присоединение.
    t56 = next(t for t in TASKS if t["key"] == "5.6")
    assert t56["field"] == "tp_term_months"
    assert hasattr(EzsSite, "tp_term_months") and hasattr(EzsTechConnection, "applicant_term_months")
