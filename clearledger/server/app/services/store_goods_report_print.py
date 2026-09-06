"""Печатный лист товарного отчёта — та же бумага, что печатает станция.

Разметка повторяет лист, к которому привыкла бухгалтерия: подчёркнутые поля
шапки, двухъярусная головка таблицы, нумерация граф «1 2 3 4 4 4 5 6» (номер 4
стоит над тремя суммовыми колонками сразу — так на бумаге), курсивные строки
остатков и разделов, подвал с приложением и двумя блоками подписей.

Один в один с `edge/agent/internal/web/assets/print_tovarny.html`: человек
печатает лист и на станции, и в центре, и лист обязан быть одним — иначе он
перестаёт его узнавать и начинает сверять глазами, тот ли это документ.
"""
from __future__ import annotations

from html import escape


def _деньги(значение) -> str:
    """Пустая графа вместо нуля: у поставщика на упрощёнке НДС именно пуст, а
    «0,00» читается как «посчитали и вышел ноль»."""
    if значение is None:
        return ""
    try:
        число = float(значение)
    except (TypeError, ValueError):
        return ""
    if abs(число) < 0.005:
        return ""
    # Разряды разделяем НЕРАЗРЫВНЫМ пробелом: на печати обычный пробел рвёт
    # число по краю графы, и «829 996,29» уезжает двумя строками.
    return f"{число:,.2f}".replace(",", " ").replace(".", ",")


_СТИЛЬ = """
/* Лист — бумага А4, а не резиновая страница: на широком мониторе таблица
   растягивалась во всю ширину и переставала быть похожей на документ, который
   потом ляжет на стол. Ширина и поля заданы в миллиметрах, экран лишь
   показывает лист на подложке. */
body{font:12px/1.35 Arial,sans-serif;color:#000;background:#e8e8e8;margin:0;
  padding:16px 0}
.лист{width:210mm;min-height:297mm;box-sizing:border-box;padding:12mm 10mm;
  margin:0 auto;background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.25)}
.шапка div{margin-bottom:10px}
.поле{display:inline-block;border-bottom:1px solid #000;min-width:330px;
  font-weight:bold;font-size:15px;padding:0 4px 1px}
.пустое{display:inline-block;border-bottom:1px solid #000;min-width:200px}
.подпись{display:block;font-size:10px;color:#333;margin-top:1px}
.номер{margin:14px 0 12px}
.период{font-weight:bold;font-size:14px;margin:10px 0 12px}
.мол{margin:0 0 14px}
.мол .поле{min-width:420px}
table{border-collapse:collapse;width:100%;font-size:11px}
th,td{border:1px solid #000;padding:2px 5px;vertical-align:top;text-align:left}
th{font-weight:normal;text-align:center}
.num{text-align:right;white-space:nowrap}
.графы td{text-align:center;font-size:10px;padding:0 2px}
.курсив td{font-style:italic;font-weight:bold}
.итог td{font-weight:bold}
.оговорка{margin:10px 0 0;font-size:10px;color:#333}
.приложение{margin:18px 0 22px}
.подписи{width:100%;border:0}
.подписи td{border:0;padding:14px 6px 0 0;vertical-align:bottom}
.линия{border-bottom:1px solid #000;min-height:18px;min-width:120px}
.печать{margin:0 0 14px}
.печать button{font:13px Arial;padding:7px 16px;cursor:pointer}
@page{size:A4 portrait;margin:8mm}
@media print{
  body{margin:0;padding:0;background:#fff;font-size:10px}
  .лист{width:auto;min-height:0;padding:0;box-shadow:none}
  .noprint{display:none}
  table{font-size:9px}
  th,td{padding:1px 3px}
  thead{display:table-header-group}
  tr{break-inside:avoid;page-break-inside:avoid}
}
"""


def лист_товарного_отчёта(данные: dict, *, организация: str,
                          подразделение: str) -> str:
    период = данные.get("period") or {}
    строки = []
    for r in данные.get("rows") or []:
        вид = r.get("kind")
        # Пояснение о неизвестном остатке — не строка бумаги, а сноска: печатаем
        # его во всю ширину, без разбивки по графам, иначе оно ляжет в колонку
        # «наименование» и обрежется.
        if вид == "сноска":
            строки.append(
                f'<tr><td colspan="8" style="font-size:10px;color:#333">'
                f'{escape(str(r.get("name") or ""))}</td></tr>')
            continue
        класс = ' class="курсив"' if вид in ("остаток", "раздел") else (
            ' class="итог"' if вид == "итог" else "")
        строки.append(
            f"<tr{класс}>"
            f"<td>{escape(str(r.get('name') or ''))}</td>"
            f"<td>{escape(str(r.get('date') or ''))}</td>"
            f"<td>{escape(str(r.get('number') or ''))}</td>"
            f"<td class=\"num\">{_деньги(r.get('purchase'))}</td>"
            f"<td class=\"num\">{_деньги(r.get('net'))}</td>"
            f"<td class=\"num\">{_деньги(r.get('vat'))}</td>"
            f"<td class=\"num\">{_деньги(r.get('margin'))}</td>"
            f"<td class=\"num\">{_деньги(r.get('retail'))}</td>"
            "</tr>")

    # Оговорки печатаются на листе, а не остаются на экране: лист подписывают,
    # и спорить потом будут по нему.
    оговорка = (
        "Остатки и приход — в розничных ценах; розничная цена берётся из снимка "
        "остатков, истории цен ни станция, ни центр не ведут. "
        "Расход — выручка магазина по видам оплаты за период, без топлива: "
        "оно учитывается своим контуром и в товарный отчёт не входит. "
        "В баланс товара расход не входит — остаток на конец считается по "
        "остаткам товара, а не выводится вычитанием.")

    подпись_блок = (
        '<td><div class="линия"></div><small class="подпись">должность</small></td>'
        '<td><div class="линия"></div><small class="подпись">подпись</small></td>'
        '<td><div class="линия"></div>'
        '<small class="подпись">расшифровка подписи</small></td>')

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Товарный отчёт</title>
<style>{_СТИЛЬ}</style></head><body>
<div class="лист">
<div class="печать noprint"><button onclick="window.print()">Печать</button></div>

<div class="шапка">
  <div><span class="поле">{escape(организация)}</span><span class="пустое"></span>
    <small class="подпись">организация</small></div>
  <div><span class="поле">{escape(подразделение)}</span><span class="пустое"></span>
    <small class="подпись">структурное подразделение</small></div>
</div>

<div class="номер"><span class="пустое"></span> ОТ <span class="пустое"></span></div>

<div class="период">Период с {escape(период.get('from', ''))} 0:00:00
  по {escape(период.get('to', ''))} 23:59:59</div>

<div class="мол">Материально ответственное лицо <span class="поле">&nbsp;</span>
  <small class="подпись" style="margin-left:210px">должность, фамилия, имя, отчество</small></div>

<table>
  <thead>
    <tr>
      <th rowspan="2">наименование</th>
      <th colspan="2">документ</th>
      <th colspan="5">сумма,</th>
    </tr>
    <tr>
      <th>дата</th><th>номер</th>
      <th>закупочная</th><th>без НДС</th><th>НДС</th><th>наценка</th><th>розничная</th>
    </tr>
    <tr class="графы">
      <td>1</td><td>2</td><td>3</td><td>4</td><td>4</td><td>4</td><td>5</td><td>6</td>
    </tr>
  </thead>
  <tbody>
{''.join(строки)}
  </tbody>
</table>

<p class="оговорка">{оговорка}</p>

<div class="приложение">Приложение
  <span class="пустое" style="min-width:260px"></span> документов</div>

<table class="подписи">
  <tr><td style="width:38%">Отчёт с документами принял и проверил</td>{подпись_блок}</tr>
  <tr><td>Материально ответственное лицо</td>{подпись_блок}</tr>
</table>
</div>
</body></html>"""
