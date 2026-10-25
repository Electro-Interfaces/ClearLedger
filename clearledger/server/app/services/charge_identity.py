"""Общие измерения отчётов ЭЗС без изменения исходной истории.

Номер CPO меняется, объект и физический порт сохраняют идентичность.
Тип клиента восстанавливается только по подтверждённым признакам: связь с
организацией, канонический тип источника, затем индивидуальный аккаунт.
Анонимная запись без этих признаков остаётся неизвестной.
"""
from sqlalchemy import case, func

from app.models import ChargeSession


def client_type(session=ChargeSession):
    corporate = func.nullif(func.btrim(session.client_name), "")
    source = func.upper(func.btrim(session.user_type))
    account = func.nullif(func.btrim(session.user_id), "")
    return case(
        (corporate.is_not(None), "ЮЛ"),
        (source.in_(("ФЛ", "ЮЛ")), source),
        (account.is_not(None), "ФЛ"),
        else_=None,
    )


def station_identity(session=ChargeSession):
    """Привязка к объекту имеет приоритет; сироты остаются отдельными кодами."""
    return case(
        (session.location_id.is_not(None), func.concat("location:", session.location_id)),
        (session.station_code.is_not(None), func.concat("code:", session.station_code)),
        else_=None,
    )


def port_identity(session=ChargeSession):
    number = func.nullif(func.btrim(session.connector_no), "")
    station = station_identity(session)
    return case(
        ((station.is_not(None)) & (number.is_not(None)), func.concat(station, "|", number)),
        else_=None,
    )
