"""Тесты PII-маскера (блокер №2, 152-ФЗ)."""
import pytest

from app.services.pii_masker import assert_no_pii, mask_text


def test_masks_email_phone_inn_kpp():
    raw = "Контакт ivan@gig.ru, тел +7 (921) 953-06-21, ИНН 7707083893 КПП 770701001."
    r = mask_text(raw, use_ner=False)
    assert "ivan@gig.ru" not in r.masked
    assert "7707083893" not in r.masked
    assert "770701001" not in r.masked
    assert "953-06-21" not in r.masked
    assert "[[EMAIL_1]]" in r.masked
    assert any(t.startswith("[[ИНН") for t in r.pii_map)
    assert any(t.startswith("[[КПП") for t in r.pii_map)


def test_long_numbers_not_split_into_inn():
    raw = "Счёт 40702810900000012345, карта 4276 3800 1234 5678."
    r = mask_text(raw, use_ner=False)
    assert "40702810900000012345" not in r.masked
    assert "4276 3800 1234 5678" not in r.masked
    # 20-значный счёт не должен распасться на ИНН-10/12
    assert any(t.startswith("[[СЧЁТ") for t in r.pii_map)
    assert any(t.startswith("[[КАРТА") for t in r.pii_map)


def test_inn12_and_passport_and_fio():
    raw = "ИП Петров П.П., ИНН 500100732259, паспорт 40 12 345678."
    r = mask_text(raw, use_ner=False)
    assert "500100732259" not in r.masked
    assert "345678" not in r.masked
    assert "Петров П.П." not in r.masked


def test_stable_token_for_same_value():
    raw = "ИНН 7707083893 и снова 7707083893."
    r = mask_text(raw, use_ner=False)
    # один и тот же ИНН → один токен → одна запись в карте
    inn_tokens = [t for t in r.pii_map if t.startswith("[[ИНН")]
    assert len(inn_tokens) == 1
    assert r.masked.count(inn_tokens[0]) == 2


def test_unmask_roundtrip():
    raw = "Почта a@b.ru, ИНН 7707083893."
    r = mask_text(raw, use_ner=False)
    assert r.unmask(r.masked) == raw


def test_assert_no_pii_blocks_raw_passes_masked():
    raw = "ИНН 7707083893"
    with pytest.raises(ValueError):
        assert_no_pii(raw)
    masked = mask_text(raw, use_ner=False).masked
    assert_no_pii(masked)  # не должно бросать


def test_empty_and_none_safe():
    assert mask_text("").masked == ""
    assert mask_text(None).masked == ""
    assert_no_pii(None)
    assert_no_pii("")
