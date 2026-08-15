"""Куда пространству можно ходить по адресу, введённому человеком.

Почтовый ящик компании настраивает сотрудник: он называет хост и порт, а
подключается к ним БЭКЕНД — изнутри стека, где рядом стоят postgres, synapse,
приложения и метаданные облака. Без ограничения форма настройки ящика работала
как сканер внутренней сети: ошибки приёма («порт закрыт», «сервер не отвечает»,
«адрес не найден») различимы, а значит отвечают на вопрос «что живёт по адресу».

Поэтому наружу — можно, внутрь — нет: приватные диапазоны, петля, link-local и
служебные имена контейнеров отбиваются до установления соединения.
"""
from __future__ import annotations

import ipaddress
import os
import socket

from fastapi import HTTPException, status

# Имена без точки — это соседи по docker-сети стека (`postgres`, `synapse`,
# `support`), а не почтовый сервер в интернете.
def _is_internal_name(host: str) -> bool:
    return "." not in host


def _is_internal_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


def _allowed_hosts() -> set[str]:
    """Хосты, которым доверяем несмотря на внутренний адрес.

    Единственный законный случай: почтовый сервер САМОЙ ПЛОЩАДКИ. Он стоит рядом,
    в той же сети, и снаружи не виден — но это наш сервер, а не сосед по стеку,
    которого называет пользователь. Разрешение задаётся ОКРУЖЕНИЕМ стека
    (`MAIL_ALLOWED_HOSTS`), то есть администратором площадки, а не формой: иначе
    любой сотрудник снял бы защиту, вписав нужное имя.
    """
    raw = os.environ.get("MAIL_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def assert_external_host(host: str | None) -> None:
    """Пустить только к внешнему хосту. Иначе — понятный отказ, а не молчание."""
    name = (host or "").strip().strip("[]")
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не указан адрес сервера")

    if name.lower() in _allowed_hosts():
        return

    if _is_internal_name(name) or _is_internal_ip(name):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Адрес указывает внутрь контейнера, а не на почтовый сервер. "
            "Укажите адрес сервера провайдера — например imap.yandex.ru")

    try:
        infos = socket.getaddrinfo(name, None)
    except socket.gaierror:
        # Несуществующий адрес разберёт сам протокол и скажет об этом человеку
        # своими словами: здесь мы решаем только вопрос «не внутрь ли стека».
        return
    for info in infos:
        if _is_internal_ip(info[4][0]):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Этот адрес разрешается во внутренний адрес контейнера — "
                "подключиться к нему из пространства нельзя")
