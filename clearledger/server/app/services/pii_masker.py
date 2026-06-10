"""PII-маскер — обязательный gate ПЕРЕД любой отправкой текста в облако (152-ФЗ).

Блокер №2 стратегии (TRADELEDGER_STRATEGY.md §7.5). До этого модуля в облако
мог уйти сырой текст с ИНН/ФИО/паспортами — недопустимо.

Контракт:
    result = mask_text(raw)
    result.masked   — текст с заменёнными ПДн на токены вида [[ИНН_1]]
    result.pii_map  — {токен: оригинал} — хранится ТОЛЬКО локально, в облако НЕ уходит

Слои:
  1. Регекс-маскирование российских ПДн (ИНН/КПП/СНИЛС/ОГРН/паспорт/счёт/карта/
     телефон/email/ФИО/организации). Всегда включён, без внешних зависимостей.
  2. NER (natasha) — имена/организации/адреса свободным текстом. Опционально:
     если пакет не установлен — слой тихо пропускается (слой 1 работает всегда).

Порядок паттернов важен: длинные числовые токены (счёт-20, карта-16, ОГРН-13/15)
обрабатываются ДО коротких (ИНН-10/12), границы \b исключают частичные совпадения.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MaskResult:
    masked: str
    pii_map: dict[str, str] = field(default_factory=dict)

    def unmask(self, text: str) -> str:
        """Локальное восстановление (НИКОГДА не вызывать на данных из облака)."""
        out = text
        for token, original in self.pii_map.items():
            out = out.replace(token, original)
        return out


# (тип, скомпилированный паттерн). Порядок = приоритет (длинные числа раньше).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Телефон РФ: +7/8 (xxx) xxx-xx-xx и слитные варианты
    ("PHONE", re.compile(r"(?<!\d)(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")),
    ("СЧЁТ", re.compile(r"\b\d{20}\b")),       # банковский счёт / корр.счёт
    ("ОГРН", re.compile(r"\b\d{15}\b")),       # ОГРНИП
    ("КАРТА", re.compile(r"\b(?:\d{4}[\s\-]?){4}\b")),  # 16 цифр платёжной карты
    ("ОГРН", re.compile(r"\b\d{13}\b")),       # ОГРН
    ("ИНН", re.compile(r"\b\d{12}\b")),        # ИНН физлица/ИП
    ("СНИЛС", re.compile(r"\b\d{3}-\d{3}-\d{3}[\s\-]\d{2}\b")),
    ("СНИЛС", re.compile(r"\b\d{11}\b")),
    ("ИНН", re.compile(r"\b\d{10}\b")),        # ИНН юрлица
    ("КПП", re.compile(r"\b\d{9}\b")),
    ("ПАСПОРТ", re.compile(r"\b\d{2}\s?\d{2}\s\d{6}\b")),  # серия+номер паспорта РФ
    # Организация: ООО/АО/ПАО/ЗАО/ОАО/НКО/ИП "Имя"
    ("ОРГ", re.compile(r'\b(?:ООО|АО|ПАО|ЗАО|ОАО|НКО|ИП)\s+[«"][^»"\n]{2,80}[»"]')),
    # ФИО: Фамилия И.О. / Фамилия И. О. / Фамилия Имя Отчество
    ("ФИО", re.compile(r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.")),
    ("ФИО", re.compile(r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|кызы|оглы|ична)\b")),
]


def _ner_spans(text: str) -> list[tuple[int, int, str]]:
    """Слой 2 (опциональный): NER через natasha. Возвращает [(start,end,type)].

    Если natasha не установлена — пустой список (gate не падает)."""
    try:
        from natasha import (  # type: ignore
            Doc, NewsEmbedding, NewsNERTagger, Segmenter,
        )
    except Exception:
        return []
    try:
        seg = Segmenter()
        tagger = NewsNERTagger(NewsEmbedding())
        doc = Doc(text)
        doc.segment(seg)
        doc.tag_ner(tagger)
        kind = {"PER": "ФИО", "ORG": "ОРГ", "LOC": "АДРЕС"}
        return [
            (s.start, s.stop, kind.get(s.type, "ПДн"))
            for s in doc.spans
            if s.type in kind
        ]
    except Exception:
        return []


def mask_text(text: str | None, *, use_ner: bool = True) -> MaskResult:
    """Замаскировать ПДн. Идемпотентен относительно уже вставленных токенов."""
    if not text:
        return MaskResult(masked=text or "", pii_map={})

    pii_map: dict[str, str] = {}
    counters: dict[str, int] = {}

    def _token(kind: str, original: str) -> str:
        # Один и тот же оригинал → один и тот же токен (стабильность).
        for tok, orig in pii_map.items():
            if orig == original:
                return tok
        counters[kind] = counters.get(kind, 0) + 1
        tok = f"[[{kind}_{counters[kind]}]]"
        pii_map[tok] = original
        return tok

    masked = text
    # Слой 1 — регекс
    for kind, pat in _PATTERNS:
        def _repl(m: re.Match[str], _k: str = kind) -> str:
            return _token(_k, m.group(0))
        masked = pat.sub(_repl, masked)

    # Слой 2 — NER (по индексам исходного текста; применяем по убыванию start,
    # чтобы смещения не «съезжали»). Пропускаем то, что уже внутри токена.
    if use_ner:
        for start, stop, kind in sorted(_ner_spans(text), key=lambda s: -s[0]):
            original = text[start:stop]
            if "[[" in original or original in pii_map.values():
                continue
            tok = _token(kind, original)
            # заменяем первое вхождение оригинала в текущем masked
            masked = masked.replace(original, tok, 1)

    return MaskResult(masked=masked, pii_map=pii_map)


def assert_no_pii(text: str | None) -> None:
    """Защитный assert для границы «в облако»: падает, если в тексте остались ПДн.

    Используется как последний рубеж ПЕРЕД сетевым вызовом — лучше отказ, чем утечка."""
    if not text:
        return
    leftover = mask_text(text, use_ner=False)
    if leftover.pii_map:
        kinds = sorted({tok.split("_")[0].strip("[]") for tok in leftover.pii_map})
        raise ValueError(
            f"В тексте остались незамаскированные ПДн ({', '.join(kinds)}) — "
            "отправка в облако заблокирована (152-ФЗ)."
        )
