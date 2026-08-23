"""Чтение боевой БП ГИГ: что уже проведено и что лежит в текущем периоде.

Это взгляд в реальную бухгалтерию, а не выгрузка и не сверка пакета. Отвечает на
вопросы, ради которых всё и затевалось: как идёт учёт, чего не хватает для
закрытия периода, что делали в прошлом и что из этого учесть сейчас. Смотрят это
в нашем приложении — расширение в 1С только грузит документы и ничего не
показывает.

**Только чтение.** В боевую базу мы не пишем ни при каких обстоятельствах:
документы туда кладёт бухгалтер расширением, разбирая нашу очередь.

⚠ Пул лицензий БП мал: второе одновременное внешнее соединение падает с «Не
обнаружено свободной лицензии». Поэтому соединение одно, живёт в COM-агенте
рядом с 1С, и мы его переиспользуем, а не открываем своё на каждый запрос.

⚠ Имена сущностей — в стиле OData (`Document_ОтчетОРозничныхПродажах`): агент
переводит их в язык запросов 1С сам. Русское «Документ.ОтчётОРозничныхПродажах»
он не понимает.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

log = logging.getLogger("clearledger.onec.read")

# Виды документов бухгалтерии, которые нас касаются. Топливо сюда не входит —
# у него свой контур и свой канал.
# Значение — подпись и признак, есть ли у вида «СуммаДокумента»: у перемещения и
# инвентаризации его нет вовсе, и запрос с ним падает целиком, а не молча.
ВИДЫ_ДОКУМЕНТОВ = {
    "Document_ОтчетОРозничныхПродажах": ("Отчёт о розничных продажах", True),
    "Document_ПоступлениеТоваровУслуг": ("Поступление товаров и услуг", True),
    "Document_ОприходованиеТоваров": ("Оприходование товаров", True),
    "Document_СписаниеТоваров": ("Списание товаров", True),
    "Document_ПеремещениеТоваров": ("Перемещение товаров", False),
    "Document_ИнвентаризацияТоваровНаСкладе": ("Инвентаризация", False),
    "Document_КомплектацияНоменклатуры": ("Комплектация номенклатуры", False),
}


class ЧтениеБПОшибка(RuntimeError):
    """Боевую базу прочитать не удалось — и сказано, почему."""


@dataclass
class ДокументБП:
    вид: str
    номер: str
    дата: str
    сумма: float
    проведён: bool
    склад: str = ""
    комментарий: str = ""


@dataclass
class СрезБП:
    """Что видно в боевой бухгалтерии на момент чтения."""

    прочитано: datetime
    организация: str = ""
    дата_запрета: date | None = None
    документы: list[ДокументБП] = field(default_factory=list)
    ошибка: str = ""

    @property
    def проведено(self) -> int:
        return sum(1 for д in self.документы if д.проведён)

    @property
    def не_проведено(self) -> int:
        return len(self.документы) - self.проведено

    @property
    def сумма(self) -> float:
        return round(sum(д.сумма for д in self.документы), 2)


class КлиентБП:
    """Тонкая обёртка над COM-агентом: соединение одно, запросы читающие."""

    def __init__(self, conn_string: str, *, agent_url: str = "", token: str = ""):
        self.conn_string = conn_string
        self.agent_url = agent_url or os.environ.get("COM_AGENT_URL", "")
        self.token = token or os.environ.get("COM_AGENT_TOKEN", "")
        if not self.agent_url:
            raise ЧтениеБПОшибка(
                "COM_AGENT_URL не задан: центр в контейнере ходит в 1С только "
                "через агента рядом с базой"
            )
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> КлиентБП:
        заголовки = {"Content-Type": "application/json"}
        if self.token:
            заголовки["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.AsyncClient(
            base_url=self.agent_url, headers=заголовки,
            timeout=httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0),
            verify=False,  # внутренний контур VPN
        )
        await self._подключиться()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _подключиться(self) -> None:
        """Подключаемся только если агент ещё не подключён.

        Повторный connect при живом соединении просит вторую лицензию и падает —
        а лицензий в БП ровно столько, сколько людей работает.
        """
        assert self._client is not None
        try:
            здоровье = (await self._client.get("/health")).json()
        except httpx.HTTPError as e:
            raise ЧтениеБПОшибка(f"COM-агент недоступен: {e}") from e
        if здоровье.get("connected"):
            return
        ответ = await self._client.post("/connect", json={"conn_string": self.conn_string})
        if ответ.status_code >= 400:
            текст = ответ.text[:300]
            if "лицензи" in текст.lower():
                raise ЧтениеБПОшибка(
                    "Свободной лицензии 1С нет: база занята людьми или другим "
                    "соединением. Читать будем следующим тактом"
                )
            raise ЧтениеБПОшибка(f"Подключение к БП отклонено [{ответ.status_code}]: {текст}")

    async def взять(self, entity: str, **параметры: Any) -> list[dict]:
        assert self._client is not None
        тело: dict[str, Any] = {"entity": entity}
        for имя, значение in параметры.items():
            if значение is not None:
                тело["filter" if имя == "filter_expr" else имя] = значение
        ответ = await self._client.post("/fetch_entity", json=тело)
        if ответ.status_code >= 400:
            log.warning("БП: %s не прочитан [%s] %s", entity,
                        ответ.status_code, ответ.text[:200])
            return []
        return ответ.json() or []


async def снять_срез(
    conn_string: str, *, date_from: date, date_to: date, виды: list[str] | None = None,
) -> СрезБП:
    """Прочитать боевую БП за период: документы, их состояние, дата запрета."""
    срез = СрезБП(прочитано=datetime.now())
    try:
        async with КлиентБП(conn_string) as бп:
            орг = await бп.взять("Catalog_Организации", select=["Наименование"], top=1)
            if орг:
                срез.организация = str(орг[0].get("Наименование") or "")

            запрет = await бп.взять(
                "InformationRegister_ДатыЗапретаИзменения",
                select=["Раздел", "ДатаЗапрета"], top=20)
            срез.дата_запрета = _граница(запрет)

            for вид in (виды or list(ВИДЫ_ДОКУМЕНТОВ)):
                подпись, есть_сумма = ВИДЫ_ДОКУМЕНТОВ.get(вид, (вид, True))
                поля = ["Номер", "Дата", "Проведен", "Комментарий"]
                if есть_сумма:
                    поля.insert(2, "СуммаДокумента")
                строки = await бп.взять(
                    вид,
                    select=поля,
                    filter_expr=(
                        f"Дата ge datetime'{date_from.isoformat()}T00:00:00' and "
                        f"Дата le datetime'{date_to.isoformat()}T23:59:59'"
                    ),
                    orderby="Дата desc", top=500,
                )
                for с in строки:
                    срез.документы.append(ДокументБП(
                        вид=подпись,
                        номер=str(с.get("Номер") or "").strip(),
                        дата=str(с.get("Дата") or "")[:10],
                        сумма=_число(с.get("СуммаДокумента")),
                        проведён=bool(с.get("Проведен")),
                        комментарий=str(с.get("Комментарий") or "")[:200],
                    ))
    except ЧтениеБПОшибка as e:
        срез.ошибка = str(e)
    except Exception as e:  # неожиданное — но экран не должен падать вместе с 1С
        log.exception("БП: срез не снят")
        срез.ошибка = f"Боевая база не прочитана: {e}"
    return срез


def _граница(записи: list[dict]) -> date | None:
    """Самая поздняя дата запрета: она и есть действующая граница."""
    даты = []
    for з in записи:
        сырое = str(з.get("ДатаЗапрета") or "")[:10]
        try:
            даты.append(date.fromisoformat(сырое))
        except ValueError:
            continue
    return max(даты) if даты else None


def _число(значение: Any) -> float:
    try:
        return round(float(значение or 0), 2)
    except (TypeError, ValueError):
        return 0.0
