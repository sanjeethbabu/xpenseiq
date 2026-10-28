from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re

from app.models import Invoice
from app.schemas import InvoiceExtraction


CENT = Decimal("0.01")


def amount(value: Decimal | int | str | None) -> Decimal:
    return Decimal(value or "0").quantize(CENT, rounding=ROUND_HALF_UP)


def cash_flow(income: Decimal, expenses: Decimal) -> Decimal:
    return amount(income - expenses)


def parse_daily_spending_scenario(question: str) -> Decimal | None:
    match = re.search(
        r"\b(?:if\s+i\s+(?:spend|spent|spending)\s+|i\s+(?:spend|spent|spending)\s+)?"
        r"(?:₹\s*|INR\s*)?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?:/|per\s+|a\s+)day\b",
        question,
        re.IGNORECASE,
    )
    if match is None:
        return None
    daily_spending = Decimal(match.group("amount").replace(",", ""))
    return amount(daily_spending) if daily_spending > 0 else None


def parse_user_available_cash(message: str) -> Decimal | None:
    match = re.search(
        r"\b(?:i\s+have\s+got|i\s+have|i['’]ve\s+got|my\s+(?:current\s+)?(?:balance|available balance|cash)\s+"
        r"(?:is|of)|available\s+(?:balance|cash)\s*(?:is|:)?|balance\s*(?:is|:))\s*"
        r"(?:₹\s*|INR\s*|Rs\.?\s*)?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\b",
        message,
        re.IGNORECASE,
    )
    if match is None:
        return None
    available_cash = Decimal(match.group("amount").replace(",", ""))
    return amount(available_cash) if available_cash >= 0 else None


def recurring_annual_cost(monthly_amount: Decimal) -> Decimal:
    return amount(monthly_amount * 12)


def project_month_end(
    month_to_date: Decimal, current_day: int, days_in_month: int
) -> dict[str, str | int]:
    elapsed_days = min(max(current_day, 1), days_in_month)
    projected_total = amount(month_to_date * days_in_month / elapsed_days)
    return {
        "days_elapsed": elapsed_days,
        "days_remaining": days_in_month - elapsed_days,
        "observed_to_date": str(amount(month_to_date)),
        "projected_month_end": str(projected_total),
        "projected_remaining": str(max(amount(projected_total - month_to_date), Decimal("0.00"))),
        "method": "Linear pace from this month's confirmed records; estimate, not a guarantee.",
    }


def forecast_spending_window(
    *,
    today: date,
    period_end: date,
    currency: str,
    month_income: Decimal,
    month_expenses: Decimal,
    recent_28_day_expenses: Decimal,
) -> dict[str, str | int | None]:
    days_ahead = max((period_end - today).days, 0)
    daily_average = amount(recent_28_day_expenses / Decimal("28"))
    recorded_net = cash_flow(month_income, month_expenses)
    remaining_budget = max(recorded_net, Decimal("0.00"))
    expected_remaining_expenses = amount(daily_average * days_ahead)
    return {
        "currency": currency,
        "period_end": period_end.isoformat(),
        "days_ahead_excluding_today": days_ahead,
        "month_income_recorded": str(amount(month_income)),
        "month_expenses_recorded": str(amount(month_expenses)),
        "recorded_net_not_bank_balance": str(recorded_net),
        "recent_28_day_expenses": str(amount(recent_28_day_expenses)),
        "recent_daily_average": str(daily_average),
        "expected_spending_at_recent_pace": str(expected_remaining_expenses),
        "optional_daily_ceiling_from_recorded_net": (
            str(amount(remaining_budget / days_ahead))
            if days_ahead and recorded_net > 0 else None
        ),
        "projected_recorded_net_at_recent_pace": str(
            cash_flow(recorded_net, expected_remaining_expenses)
        ),
        "method": (
            "Recent daily pace is the recorded expense total for the 28 complete calendar days before today "
            "divided by 28. This scenario assumes that pace continues through the target date and no future "
            "income is added. The optional daily ceiling divides positive month-to-date recorded net by the "
            "remaining days; it is not a bank balance or a guarantee of affordability."
        ),
    }


def is_in_period(value: date | None, start: date, end: date) -> bool:
    return value is not None and start <= value <= end


def has_duplicate_invoice(
    payload: InvoiceExtraction, candidates: list[Invoice]
) -> bool:
    if (
        not payload.invoice_number
        or not payload.invoice_date
        or payload.total is None
        or not payload.seller_gstin and not payload.seller_name
    ):
        return False
    invoice_number = re.sub(r"[^a-z0-9]", "", payload.invoice_number.casefold())
    seller_identity = re.sub(
        r"[^a-z0-9]", "", (payload.seller_gstin or payload.seller_name or "").casefold()
    )
    if not seller_identity:
        return False
    return any(
        re.sub(r"[^a-z0-9]", "", (candidate.invoice_number or "").casefold()) == invoice_number
        and re.sub(
            r"[^a-z0-9]",
            "",
            (candidate.seller_gstin or candidate.seller_name or "").casefold(),
        ) == seller_identity
        for candidate in candidates
    )
