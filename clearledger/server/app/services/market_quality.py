"""Общие правила достоверности рейтинга открытого реестра."""
from math import isfinite
from sqlalchemy import and_, case


def observed_rating(value, reviews_count) -> float | None:
    """Технический ноль без отзывов не является пользовательской оценкой."""
    if value is None or reviews_count is None:
        return None
    try:
        rating, count = float(value), int(reviews_count)
    except (TypeError, ValueError, OverflowError):
        return None
    return rating if count > 0 and isfinite(rating) and 0 <= rating <= 5 else None


def rating_expression(rating, reviews_count):
    """То же правило для агрегатов SQL, включая ранее загруженные данные."""
    return case((and_(reviews_count > 0, rating >= 0, rating <= 5), rating), else_=None)
