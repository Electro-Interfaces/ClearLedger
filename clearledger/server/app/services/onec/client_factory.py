"""Каким транспортом ходить в 1С — одно решение на весь бэкенд.

COM-объект 1С живёт только на Windows рядом с базой, поэтому у нас два пути:
  • `OneCComClient` — subprocess `com_worker` на той же машине (dev на Windows);
  • `OneCHttpAgentClient` — HTTP к агенту на 1c-dev-01 (бэкенд в контейнере на Linux).

Решает переменная `COM_AGENT_URL`. Раньше это условие было только в `sync_service`, а
`channel_orchestrator` звал COM напрямую — поэтому канал ЦБ (сопутка/общепит и остатки)
из контейнера не работал вовсе, и данные Магазина замирали на дате последней выгрузки.
"""
from __future__ import annotations

import os
from typing import Any


def make_onec_client(conn_string: str) -> Any:
    """Клиент 1С для текущего окружения. Интерфейс у обоих одинаковый."""
    if os.environ.get("COM_AGENT_URL"):
        from app.services.onec.http_agent_client import OneCHttpAgentClient
        return OneCHttpAgentClient(conn_string)
    from app.services.onec.com_client import OneCComClient
    return OneCComClient(conn_string)
