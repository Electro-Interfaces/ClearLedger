"""Заявка на технологическое присоединение — печатная форма из данных проекта.

Перечень сведений — п. 12.1 Правил ТП (ПП РФ №861) в разборе энергетика от
07.10.2026: юрлицо, один источник, до 150 кВт включительно. Реквизиты заявителя
берутся из карточки нашего юрлица, параметры — из вкладки «Присоединение».

Отдаём HTML, печатает браузер — как бланки «Трека» (`doc_print`). Чего в данных
нет, в форме остаётся прочерком под ручку, а над бланком (на экране, не в печати)
перечислено, что не заполнено: заявка с пропуском не должна выглядеть готовой.
"""
from __future__ import annotations

import html
from typing import Any

BLANK = "________________"
DEFAULT_VOLTAGE = "0,4"
DEFAULT_RELIABILITY = "III"
DEFAULT_LOAD = "Электрозарядная станция"

_CSS = """
@page { size: A4; margin: 20mm 15mm; }
body { font-family: 'Times New Roman', serif; font-size: 12pt; color: #000; max-width: 180mm; margin: 0 auto; }
.to { margin-left: 55%; margin-bottom: 18pt; }
h1 { font-size: 13pt; text-align: center; margin: 12pt 0; }
p { margin: 6pt 0; text-align: justify; }
ol { padding-left: 16pt; } li { margin: 3pt 0; }
.sign { margin-top: 24pt; } .small { font-size: 10pt; }
.gaps { font-family: Arial, sans-serif; font-size: 10pt; background: #fff3cd; border: 1px solid #e0c060;
        padding: 6pt 8pt; margin-bottom: 14pt; }
@media print { .gaps { display: none; } }
"""


def _num(value: Any) -> str:
    return f"{float(value):g}".replace(".", ",") if value not in (None, "") else ""


def render(org: Any, site: Any, tc: Any, kit: list[dict[str, Any]]) -> str:
    """HTML заявки. `org` — карточка юрлица или None; `kit` — комплект с отметкой наличия."""
    gaps: list[str] = []

    def val(value: Any, label: str) -> str:
        if value in (None, ""):
            gaps.append(label)
            return BLANK
        return html.escape(str(value))

    name = val(org and (org.full_name or org.name), "полное наименование заявителя")
    ogrn = val(org and org.ogrn, "ОГРН")
    inn = val(org and org.inn, "ИНН")
    kpp = html.escape(org.kpp) if org and org.kpp else ""
    legal = val(org and org.legal_address, "юридический адрес")
    postal = val(org and (org.postal_address or org.legal_address), "почтовый адрес")
    operator = val(tc.grid_operator, "сетевая организация")
    address = val(site.full_address or site.address or site.install_place, "адрес объекта")
    new_power = tc.power_kwt if tc.power_kwt is not None else site.planned_power_kwt
    old_power = tc.existing_power_kwt or 0
    power = val(_num(new_power), "запрашиваемая мощность")
    total = _num((new_power or 0) + old_power) if new_power is not None else BLANK
    supplier = val(tc.energy_supplier, "сбытовая организация")
    director = val(org and org.director_name, "руководитель заявителя")
    position = html.escape((org and org.director_position) or "Руководитель")
    contacts = ", ".join(html.escape(x) for x in ((org and org.phone), (org and org.email)) if x)
    if not contacts:
        gaps.append("телефон или адрес электронной почты")
    voltage = html.escape(tc.voltage or DEFAULT_VOLTAGE)
    obj = html.escape(site.title or DEFAULT_LOAD)
    attached = "".join(f"<li>{html.escape(d['label'])}</li>" for d in kit if d["present"])
    missing = [d["label"] for d in kit if not d["present"] and not d["optional"]]
    if missing:
        gaps.append("не приложены: " + "; ".join(missing))

    gaps_html = (f'<div class="gaps"><b>Не заполнено:</b> {html.escape(", ".join(gaps))}. '
                 "В печать этот блок не попадает.</div>") if gaps else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Заявка на технологическое присоединение</title><style>{_CSS}</style></head><body>
{gaps_html}
<div class="to">В {operator}</div>
<h1>ЗАЯВКА<br>юридического лица на присоединение по одному источнику электроснабжения
энергопринимающих устройств с максимальной мощностью до 150 кВт включительно</h1>
<p>1. Заявитель: {name}, ОГРН {ogrn}, ИНН {inn}{f", КПП {kpp}" if kpp else ""}.</p>
<p>2. Место нахождения заявителя: {legal}. Почтовый адрес: {postal}.</p>
<p>3. В связи с новым строительством просит осуществить технологическое присоединение
энергопринимающих устройств: {obj}, расположенных по адресу: {address}.</p>
<p>4. Максимальная мощность энергопринимающих устройств (присоединяемых и ранее присоединённых)
составляет {total} кВт при напряжении {voltage} кВ, в том числе:<br>
а) максимальная мощность присоединяемых энергопринимающих устройств — {power} кВт при напряжении {voltage} кВ;<br>
б) максимальная мощность ранее присоединённых энергопринимающих устройств — {_num(old_power)} кВт.</p>
<p>5. Заявляемая категория надёжности энергопринимающих устройств — {html.escape(tc.reliability_category or DEFAULT_RELIABILITY)}
(по одному источнику электроснабжения).</p>
<p>6. Характер нагрузки (вид экономической деятельности): {html.escape(tc.load_kind or DEFAULT_LOAD)}.</p>
<p>7. Сроки проектирования и поэтапного введения в эксплуатацию: срок проектирования {BLANK},
срок введения в эксплуатацию {BLANK}, максимальная мощность {power} кВт, категория надёжности
{html.escape(tc.reliability_category or DEFAULT_RELIABILITY)}.</p>
<p>8. Гарантирующий поставщик (энергосбытовая организация), с которым планируется заключение
договора энергоснабжения: {supplier}.</p>
<p>Приложения:</p><ol>{attached or f"<li>{BLANK}</li>"}</ol>
<table class="sign" width="100%"><tr>
<td>{position}</td><td>_______________</td><td>{director}</td></tr></table>
<p class="small">Контакты: {contacts or BLANK}</p>
<p class="small">Дата: «____» ____________ 20__ г. &nbsp; М.П.</p>
</body></html>"""
