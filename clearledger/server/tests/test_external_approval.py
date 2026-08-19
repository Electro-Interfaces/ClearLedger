"""Право внешнего участника: что именно ограничивает ссылку на визу.

Проверяется не «работает ли согласование» — это делает сам движок виз, — а
границы права. Каждая из них существует потому, что без неё ссылка перестаёт быть
разрешением на одну активность и становится доступом: пересланная ссылка даёт
вторую подпись, ссылка на просмотр начинает подписывать, отзыв срабатывает
задним числом.
"""

from datetime import datetime, timezone

import pytest

from app.services.external_approval import (
    APPROVE_TEXT, DEFAULT_TTL_DAYS, MAX_TTL_DAYS, ExternalActor,
    ExternalApprovalError, REJECT_TEXT, guard,
)


class FakeLink:
    def __init__(self, purpose="approve", approval_id="a", used_at=None):
        self.purpose = purpose
        self.approval_id = approval_id
        self.used_at = used_at


def test_ssylka_na_prosmotr_ne_podpisyvaet():
    """Показ и подпись — разные права, и первое не превращается во второе."""
    with pytest.raises(ExternalApprovalError):
        guard(FakeLink(purpose="view", approval_id=None))


def test_ssylka_bez_shaga_ne_podpisyvaet():
    """Назначение без адресата — ошибка выпуска, а не «подпиши что-нибудь»."""
    with pytest.raises(ExternalApprovalError):
        guard(FakeLink(purpose="approve", approval_id=None))


def test_ispolzovannaya_ssylka_mertva():
    """Иначе пересланная ссылка превращается во вторую подпись под одним шагом."""
    with pytest.raises(ExternalApprovalError):
        guard(FakeLink(used_at=datetime.now(timezone.utc)))


def test_zhivaya_ssylka_prohodit():
    guard(FakeLink())  # не бросает


def test_poryadok_proverok_ne_vydayot_lishnego():
    """Ссылка для просмотра отвечает «не даёт права», а не «уже использована».

    Второй ответ подсказывал бы, что где-то есть и ссылка на подпись, — а это
    сведения о документообороте компании, которых у постороннего быть не должно.
    """
    link = FakeLink(purpose="view", approval_id=None, used_at=datetime.now(timezone.utc))
    with pytest.raises(ExternalApprovalError) as exc:
        guard(link)
    assert "согласовывать" in str(exc.value)


def test_srok_ogranichen_s_oboih_storon():
    """Ссылка без срока — утечка, отложенная во времени; слишком длинная — тоже."""
    assert 1 <= DEFAULT_TTL_DAYS <= MAX_TTL_DAYS
    assert MAX_TTL_DAYS <= 90


def test_teksty_soglasiya_razlichayutsya_i_nepusty():
    """Согласие и отказ — разные утверждения, и в доказательство идёт нужное."""
    assert APPROVE_TEXT != REJECT_TEXT
    assert "согласов" in APPROVE_TEXT.lower()
    assert "отказ" in REJECT_TEXT.lower()


def test_vneshniy_uchastnik_ne_imeet_uchyotki():
    """`id` пуст — и это видно в следе: подписал человек без учётной записи."""
    actor = ExternalActor(name="Иванов И. И.", email="ivanov@example.com")
    assert actor.id is None
