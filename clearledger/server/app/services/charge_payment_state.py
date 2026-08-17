from sqlalchemy import func, select

from app.models import ChargePayment, ChargeSession


def confirmed_payment_at(session=ChargeSession):
    return (
        select(func.max(ChargePayment.paid_at))
        .where(
            ChargePayment.company_id == session.company_id,
            ChargePayment.session_ext_id == session.session_ext_id,
            ChargePayment.bank_txn_id.is_not(None),
        )
        .correlate(session)
        .scalar_subquery()
    )


def effective_paid_at(session=ChargeSession):
    return func.coalesce(session.paid_at, confirmed_payment_at(session))
