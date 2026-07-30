import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import EzsSite
from app.services.ezs_project import _stage_position_sql
from app.services.ezs_sites import STAGE_ORDER, _risk_conditions


def test_sql_позиции_не_принимает_произвольную_колонку():
    sql = _stage_position_sql("e.to_stage")
    assert "case e.to_stage" in sql
    for position, stage in enumerate(STAGE_ORDER):
        assert f"when '{stage}' then {position}" in sql
    with pytest.raises(ValueError):
        _stage_position_sql("stage); drop table ezs_sites; --")


@pytest.mark.parametrize(
    "risk,table",
    [
        ("no_history", "ezs_site_events"),
        ("no_participants", "ezs_site_participants"),
        ("rework", "ezs_site_events"),
        ("commissioning_mismatch", "ezs_sites"),
    ],
)
def test_исключения_обзора_раскрываются_тем_же_фильтром(risk, table):
    query = select(EzsSite.id).where(*_risk_conditions(risk))
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert table in sql
