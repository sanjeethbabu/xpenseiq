import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import fitz
import pytest
from fastapi import HTTPException
from PIL import Image
from pytesseract import TesseractError, TesseractNotFoundError
from sqlalchemy.dialects import postgresql

from app.documents import extract_text, render_pdf_page
from app.finance import amount, cash_flow, forecast_spending_window, is_in_period, parse_daily_spending_scenario, parse_user_available_cash, project_month_end, recurring_annual_cost
from app.ai import answer_financial_question
from app.main import (
    confirm_document,
    document_details,
    document_out,
    document_preview_path,
    has_duplicate_invoice,
    invoice_values,
    spending_over_time,
    upload_document,
)
from app.models import Invoice, InvoiceItem
from app.schemas import BudgetCreate, EmployeeCreate, InvoiceExtraction, PasswordChange, ReimbursementDecision, ReimbursementTeamCreate, UserLogin
from app.core.config import Settings
from app import worker


def test_money_uses_decimal_rounding():
    assert amount(Decimal("12.345")) == Decimal("12.35")


def test_cash_flow_is_income_less_recorded_expenses():
    assert cash_flow(Decimal("1200.00"), Decimal("425.50")) == Decimal("774.50")


@pytest.mark.parametrize(
    ("period_type", "period_index", "expected_start", "expected_end", "expected_title"),
    [
        ("quarter", 1, date(2024, 1, 1), date(2024, 3, 31), "Q1 2024"),
        ("quarter", 4, date(2024, 10, 1), date(2024, 12, 31), "Q4 2024"),
        ("half_year", 1, date(2024, 1, 1), date(2024, 6, 30), "H1 2024"),
        ("half_year", 2, date(2024, 7, 1), date(2024, 12, 31), "H2 2024"),
        ("year", 0, date(2024, 1, 1), date(2024, 12, 31), "2024"),
    ],
)
def test_budget_periods_use_calendar_dates(
    period_type, period_index, expected_start, expected_end, expected_title
):
    from app.main import budget_period_dates

    assert budget_period_dates(period_type, 2024, period_index) == (
        expected_start,
        expected_end,
        expected_title,
    )


def test_budget_schema_normalizes_currency_and_rejects_invalid_period():
    budget = BudgetCreate(
        period_type="half_year",
        period_index=2,
        year=2026,
        currency="inr",
        amount="50000.00",
    )
    assert budget.currency == "INR"
    assert budget.amount == Decimal("50000.00")
    with pytest.raises(ValueError, match="valid quarter"):
        BudgetCreate(period_type="quarter", period_index=0, year=2026, amount="1000")
    with pytest.raises(ValueError, match="valid quarter"):
        BudgetCreate(period_type="year", period_index=1, year=2026, amount="1000")


def test_reimbursement_team_and_employee_inputs_are_normalized():
    assert ReimbursementTeamCreate(name="  Operations  ").name == "Operations"
    employee = EmployeeCreate(
        display_name="  Alex Morgan  ",
        email="Alex.Morgan@example.com",
    )
    assert employee.display_name == "Alex Morgan"
    assert employee.email == "alex.morgan@example.com"
    assert UserLogin(email=" emp001 ", password="EMP001").email == "emp001"
    assert PasswordChange(new_password="a-secure-new-password").new_password == "a-secure-new-password"
    with pytest.raises(ValueError, match="team name"):
        ReimbursementTeamCreate(name="  ")
    with pytest.raises(ValueError, match="at least 8 characters"):
        PasswordChange(new_password="EMP001")


def test_reimbursement_rejection_requires_a_reason():
    with pytest.raises(ValueError, match="reason when rejecting"):
        ReimbursementDecision(action="reject", note="  ")
    decision = ReimbursementDecision(action="reject", note="Not a business expense")
    assert decision.note == "Not a business expense"
    assert ReimbursementDecision(action="approve").note is None


@pytest.mark.parametrize(("role", "claim_owner"), [("employee", False), ("owner", True)])
def test_reimbursement_claims_cannot_be_reviewed_by_employees_or_the_claimant(role, claim_owner):
    from app.main import decide_reimbursement_claim

    user_id = uuid4()
    team_id = uuid4()
    claim = SimpleNamespace(employee_id=user_id if claim_owner else uuid4(), status="submitted")

    class FakeDatabase:
        def __init__(self):
            self.results = [SimpleNamespace(role=role, team_id=team_id)]
            if claim_owner:
                self.results.append(claim)
            self.committed = False

        def scalar(self, _query):
            return self.results.pop(0)

        def commit(self):
            self.committed = True

    database = FakeDatabase()
    with pytest.raises(HTTPException) as error:
        decide_reimbursement_claim(
            uuid4(),
            ReimbursementDecision(action="approve"),
            SimpleNamespace(id=user_id),
            database,
        )
    assert error.value.status_code == 403
    assert not database.committed


def test_employee_can_log_in_with_assigned_id(monkeypatch):
    from app import main
    from app.security import hash_password

    employee = SimpleNamespace(
        id=uuid4(),
        email="employee@example.com",
        display_name="Employee",
        employee_id="EMP001",
        must_change_password=True,
        password_hash=hash_password("EMP001"),
    )

    class FakeDatabase:
        def scalar(self, query):
            statement = str(query.compile(dialect=postgresql.dialect()))
            assert "users.employee_id" in statement
            assert "EMP001" in query.compile(dialect=postgresql.dialect()).params.values()
            return employee

    monkeypatch.setattr(main, "set_session", lambda _response, _user_id: None)
    assert main.login(
        UserLogin(email=" emp001 ", password="EMP001"),
        SimpleNamespace(),
        FakeDatabase(),
    ) is employee


def test_temporary_password_must_be_changed_before_protected_api_use(monkeypatch):
    from app.security import current_user

    user_id = uuid4()
    employee = SimpleNamespace(id=user_id, must_change_password=True)

    class FakeDatabase:
        def get(self, _model, requested_id):
            assert requested_id == user_id
            return employee

    monkeypatch.setattr("app.security.jwt.decode", lambda *_args, **_kwargs: {"sub": str(user_id)})
    request = SimpleNamespace(
        cookies={"xpenziq_session": "test-token"},
        url=SimpleNamespace(path="/api/v1/expenses"),
    )
    with pytest.raises(HTTPException) as error:
        current_user(request, FakeDatabase())
    assert error.value.status_code == 403
    request.url.path = "/api/v1/auth/me"
    assert current_user(request, FakeDatabase()) is employee


def test_create_budget_returns_period_dates_and_rejects_duplicate_period():
    from app import main

    user = SimpleNamespace(id=uuid4())

    class FakeDatabase:
        def __init__(self, duplicate=None):
            self.duplicate = duplicate
            self.saved = None

        def scalar(self, _query):
            return self.duplicate

        def add(self, budget):
            budget.id = uuid4()
            self.saved = budget

        def commit(self):
            pass

        def refresh(self, _budget):
            pass

    payload = BudgetCreate(
        period_type="quarter",
        period_index=1,
        year=2026,
        amount="25000.00",
    )
    database = FakeDatabase()
    created = main.create_budget(payload, user, database)
    assert created["title"] == "Q1 2026"
    assert created["start_date"] == "2026-01-01"
    assert created["end_date"] == "2026-03-31"
    assert created["remaining_amount"] == "25000.00"

    with pytest.raises(HTTPException) as error:
        main.create_budget(payload, user, FakeDatabase(duplicate=uuid4()))
    assert error.value.status_code == 409


def test_list_budgets_calculates_user_currency_spending_and_remaining_amount():
    from app import main
    from app.models import Budget

    user_id = uuid4()
    budget = Budget(
        id=uuid4(),
        user_id=user_id,
        period_type="quarter",
        period_index=1,
        year=2026,
        currency="INR",
        amount=Decimal("10000.00"),
    )

    class FakeDatabase:
        def scalars(self, query):
            compiled = query.compile(dialect=postgresql.dialect())
            assert "budgets.user_id" in str(compiled)
            assert user_id in compiled.params.values()
            return SimpleNamespace(all=lambda: [budget])

        def scalar(self, query):
            compiled = query.compile(dialect=postgresql.dialect())
            statement = str(compiled)
            assert "invoices.currency" in statement
            assert "invoices.invoice_date" in statement
            assert user_id in compiled.params.values()
            return Decimal("2750.50")

    result = main.list_budgets(SimpleNamespace(id=user_id), FakeDatabase())
    assert result["items"][0]["expense_amount"] == "2750.50"
    assert result["items"][0]["remaining_amount"] == "7249.50"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("if i spent 200 per day what happens?", Decimal("200.00")),
        ("What if I spend ₹1,250 a day?", Decimal("1250.00")),
        ("Could I spend 50/day?", Decimal("50.00")),
        ("How much did I spend last month?", None),
    ],
)
def test_parse_daily_spending_scenario(question, expected):
    assert parse_daily_spending_scenario(question) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("i have 20000 now", Decimal("20000.00")),
        ("My available balance is ₹12,500.50", Decimal("12500.50")),
        ("I have got Rs. 800", Decimal("800.00")),
        ("I spent 200 today", None),
    ],
)
def test_parse_user_reported_available_cash(message, expected):
    assert parse_user_available_cash(message) == expected


def test_recurring_annual_cost_is_explicitly_annualized():
    assert recurring_annual_cost(Decimal("49.99")) == Decimal("599.88")


def test_month_end_projection_is_linear_and_reports_remaining_pace():
    projection = project_month_end(Decimal("1000"), current_day=10, days_in_month=30)
    assert projection["observed_to_date"] == "1000.00"
    assert projection["projected_month_end"] == "3000.00"
    assert projection["projected_remaining"] == "2000.00"
    assert projection["days_remaining"] == 20
    assert "not a guarantee" in projection["method"]


def test_month_end_projection_handles_zero_spending_and_month_end():
    projection = project_month_end(Decimal("0"), current_day=31, days_in_month=31)
    assert projection["projected_month_end"] == "0.00"
    assert projection["projected_remaining"] == "0.00"
    assert projection["days_remaining"] == 0


def test_weekly_forecast_calculates_recorded_net_and_daily_ceiling():
    forecast = forecast_spending_window(
        today=date(2026, 10, 13),
        period_end=date(2026, 10, 18),
        currency="INR",
        month_income=Decimal("12000"),
        month_expenses=Decimal("5000"),
        recent_28_day_expenses=Decimal("5600"),
    )
    assert forecast["days_ahead_excluding_today"] == 5
    assert forecast["recorded_net_not_bank_balance"] == "7000.00"
    assert forecast["recent_daily_average"] == "200.00"
    assert forecast["expected_spending_at_recent_pace"] == "1000.00"
    assert forecast["optional_daily_ceiling_from_recorded_net"] == "1400.00"
    assert forecast["projected_recorded_net_at_recent_pace"] == "6000.00"


def test_weekly_forecast_does_not_invent_budget_when_recorded_net_is_nonpositive():
    forecast = forecast_spending_window(
        today=date(2026, 10, 13),
        period_end=date(2026, 10, 18),
        currency="INR",
        month_income=Decimal("1000"),
        month_expenses=Decimal("1200"),
        recent_28_day_expenses=Decimal("0"),
    )
    assert forecast["optional_daily_ceiling_from_recorded_net"] is None


def test_forecast_question_uses_user_scoped_currency_data_and_sunday_horizon(monkeypatch):
    from app import main
    from app.schemas import AssistantQuestion

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 13)

    class FakeDatabase:
        def __init__(self):
            self.rows = [
                [("INR", Decimal("2000")), ("USD", Decimal("100"))],
                [("INR", Decimal("3000"))],
                [("INR", Decimal("2800")), ("USD", Decimal("280"))],
            ]
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            rows = self.rows.pop(0)
            return SimpleNamespace(all=lambda: rows)

    captured = {}

    async def fake_answer(question, metrics, history):
        captured.update(question=question, metrics=metrics, history=history)
        return "Here’s a careful spending estimate."

    monkeypatch.setattr(main, "date", FrozenDate)
    monkeypatch.setattr(main, "answer_financial_question", fake_answer)
    monkeypatch.setattr(main, "overview", lambda *_args: pytest.fail("Forecast used the broad account overview"))
    user = SimpleNamespace(id=uuid4(), preferred_currency="INR")
    database = FakeDatabase()
    payload = AssistantQuestion(question="How should I spend the rest of my money through this weekend?")

    response = asyncio.run(main.ask_financial_question(payload, user, database))

    assert response["answer"] == "Here’s a careful spending estimate."
    assert len(database.statements) == 3
    assert all("user_id" in str(statement) for statement in database.statements)
    forecast = response["metrics"]["forecast"]
    assert forecast["INR"]["period_end"] == "2026-10-18"
    assert forecast["INR"]["expected_spending_at_recent_pace"] == "500.00"
    assert forecast["INR"]["optional_daily_ceiling_from_recorded_net"] == "200.00"
    assert forecast["USD"]["recorded_net_not_bank_balance"] == "-100.00"
    assert forecast["USD"]["optional_daily_ceiling_from_recorded_net"] is None
    assert "not a bank balance" in captured["metrics"]["important_limit"]


def test_daily_spending_followup_answers_against_prior_weekend_forecast(monkeypatch):
    from app import main
    from app.schemas import AssistantQuestion, AssistantMessage

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 13)

    class FakeDatabase:
        rows = [
            [("INR", Decimal("3000"))],
            [("INR", Decimal("5000"))],
            [("INR", Decimal("2531.10"))],
        ]

        def execute(self, _statement):
            return SimpleNamespace(all=lambda: self.rows.pop(0))

    monkeypatch.setattr(main, "date", FrozenDate)
    captured = {}

    async def fake_answer(question, metrics, history):
        captured.update(question=question, metrics=metrics, history=history)
        return "A tailored answer based on the scenario calculations."

    monkeypatch.setattr(main, "answer_financial_question", fake_answer)
    user = SimpleNamespace(id=uuid4(), preferred_currency="INR")
    payload = AssistantQuestion(
        question="if i spent 200 per day what happens?",
        history=[
            AssistantMessage(
                role="user",
                content="How do I spend my rest of money to cross this week end?",
            ),
            AssistantMessage(
                role="assistant",
                content="Your recent daily average is about ₹90 per day.",
            ),
        ],
    )

    response = asyncio.run(main.ask_financial_question(payload, user, FakeDatabase()))

    assert response["answer"] == "A tailored answer based on the scenario calculations."
    assert captured["question"] == payload.question
    assert len(captured["history"]) == 2
    scenario = captured["metrics"]["forecast"]["INR"]["scenario_analysis"]
    assert scenario["assumed_daily_spending"] == "200.00"
    assert scenario["days_in_scenario"] == 5
    assert scenario["target_date"] == "2026-10-18"
    assert scenario["estimated_total_spending"] == "1000.00"
    assert scenario["recent_pace_estimated_total_for_same_period"] == "452.00"
    assert scenario["difference_vs_recent_pace"] == "548.00"
    assert scenario["recorded_net_after_scenario_not_bank_balance"] == "1000.00"


def test_cash_and_advice_followups_use_forecast_horizon_and_reported_balance(monkeypatch):
    from app import main
    from app.schemas import AssistantMessage, AssistantQuestion

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 13)

    class FakeDatabase:
        rows = [
            [("INR", Decimal("3000"))],
            [("INR", Decimal("5000"))],
            [("INR", Decimal("2531.10"))],
        ]

        def execute(self, _statement):
            return SimpleNamespace(all=lambda: self.rows.pop(0))

    captured = {}

    async def fake_answer(question, metrics, history):
        captured.update(question=question, metrics=metrics, history=history)
        return "Tailored financial guidance."

    monkeypatch.setattr(main, "date", FrozenDate)
    monkeypatch.setattr(main, "answer_financial_question", fake_answer)
    monkeypatch.setattr(main, "overview", lambda *_args: pytest.fail("Follow-up used the broad account overview"))
    payload = AssistantQuestion(
        question="what is your suggestion?",
        history=[
            AssistantMessage(role="user", content="How much can I spend through this weekend?"),
            AssistantMessage(role="assistant", content="Your recent daily average is about ₹90 per day."),
            AssistantMessage(role="user", content="I have 20000 now"),
            AssistantMessage(role="assistant", content="Thanks, I’ll use that as your current reported amount."),
        ],
    )

    response = asyncio.run(
        main.ask_financial_question(
            payload,
            SimpleNamespace(id=uuid4(), preferred_currency="INR"),
            FakeDatabase(),
        )
    )

    assert response["answer"] == "Tailored financial guidance."
    assert captured["question"] == payload.question
    reported = captured["metrics"]["forecast"]["INR"]["user_reported_available_cash"]
    assert reported["amount"] == "20000.00"
    assert reported["currency"] == "INR"
    assert reported["daily_equivalent_before_upcoming_bills"] == "4000.00"
    assert "not independently verified" in reported["basis"]


def test_assistant_history_accepts_a_full_length_stark_response():
    from app.schemas import AssistantMessage, AssistantQuestion

    long_text = "x" * 5000
    assert len(AssistantMessage(role="assistant", content=long_text).content) == 5000
    payload = AssistantQuestion(
        question=long_text,
        history=[AssistantMessage(role="user", content=long_text)],
    )
    assert len(payload.question) == 5000
    assert len(payload.history[0].content) == 5000


def test_financial_assistant_prompt_covers_item_details_features_and_forecasts(monkeypatch):
    from app import ai

    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "Grounded answer"

    monkeypatch.setattr(ai, "_chat", fake_chat)
    answer = asyncio.run(answer_financial_question(
        "Which one was it?",
        {"highest_line_items": []},
        [{"role": "user", "content": "What did I buy for the most?"}],
    ))

    assert answer == "Grounded answer"
    system_message = captured["messages"][0]["content"]
    assert "website notes" in system_message
    assert "line totals" in system_message
    assert "estimates" in system_message
    assert "untrusted" in system_message
    assert "natural chat" in system_message
    assert "forecast expert" in system_message
    assert captured["kwargs"]["max_completion_tokens"] == 480
    assert captured["messages"][1] == {"role": "user", "content": "What did I buy for the most?"}
    assert captured["messages"][2]["content"].endswith("Current question: Which one was it?")


def test_invoice_extraction_prompt_requires_complete_receipt_item_fields(monkeypatch):
    import json

    from app import ai

    receipt_text = """FreshMart
    SALES INVOICE
    Amul Butter (200g) 1 62.00 62.00
    Aashirvaad Atta (5kg) 1 245.00 245.00
    Fortune Sunflower 0il(1L) 1 178.00. 178.00
    Maggi Noodles (Pack of 4) 1 72.00 72.00
    Dettol Handwash (250m1) 1 145.00 145.00,
    Sub Total % 702.00
    Discount = 20.00
    Total Amount & 682.00"""
    line_items = [
        {"description": "Amul Butter (200g)", "category": "Groceries & Dining", "quantity": 1, "unit": None, "unit_price": None, "line_total": None},
        {"description": "Aashirvaad Atta (5kg)", "category": "Groceries & Dining", "quantity": 1, "unit": None, "unit_price": None, "line_total": None},
        {"description": "Fortune Sunflower Oil (1L)", "category": "Groceries & Dining", "quantity": 1, "unit": None, "unit_price": None, "line_total": None},
        {"description": "Maggi Noodles (Pack of 4)", "category": "Groceries & Dining", "quantity": 1, "unit": None, "unit_price": None, "line_total": None},
        {"description": "Dettol Handwash (250ml)", "category": "Groceries & Dining", "quantity": 1, "unit": None, "unit_price": None, "line_total": None},
    ]
    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return json.dumps({
            "document_type": "receipt",
            "currency": "INR",
            "seller_name": "FreshMart Supermarket",
            "subtotal": 702,
            "discount_total": 20,
            "total": 682,
            "line_items": line_items,
        })

    monkeypatch.setattr(ai, "_chat", fake_chat)
    extracted = asyncio.run(ai.extract_invoice(receipt_text))

    assert len(extracted.line_items) == 5
    assert {item.category for item in extracted.line_items} == {"Groceries & Dining"}
    assert [
        (item.quantity, item.unit, item.unit_price, item.line_total)
        for item in extracted.line_items
    ] == [
        (Decimal("1.000"), "200g", Decimal("62.00"), Decimal("62.00")),
        (Decimal("1.000"), "5kg", Decimal("245.00"), Decimal("245.00")),
        (Decimal("1.000"), "1L", Decimal("178.00"), Decimal("178.00")),
        (Decimal("1.000"), "Pack of 4", Decimal("72.00"), Decimal("72.00")),
        (Decimal("1.000"), "250ml", Decimal("145.00"), Decimal("145.00")),
    ]
    prompt = captured["messages"][0]["content"]
    assert "LINE ITEM COMPLETENESS IS REQUIRED" in prompt
    assert "Map Qty/Quantity to quantity" in prompt
    assert "Rate/Unit Price/Price to unit_price" in prompt
    assert "Amount/Line Total/Value to line_total" in prompt
    assert "Extract a printed package size or measure" in prompt
    assert "CATEGORIZE EVERY LINE ITEM INDIVIDUALLY" in prompt
    assert "never assign Other to every row just because the invoice has mixed spending" in prompt
    assert "62.00 62.00" in captured["messages"][1]["content"]
    assert captured["messages"][1]["content"].endswith(receipt_text)
    assert captured["kwargs"]["json_mode"] is True


def test_mixed_invoice_keeps_distinct_line_item_categories():
    from app.ai import _validate_extraction_for_review

    invoice = _validate_extraction_for_review({
        "category": "Other",
        "line_items": [
            {"description": "Train tickets", "category": "Travel", "line_total": "25800.00"},
            {"description": "Team stay", "category": "Stay", "line_total": "14400.00"},
            {"description": "Team jersey", "category": "Clothing", "line_total": "12750.00"},
            {"description": "Track suit", "category": "Clothing", "line_total": "18000.00"},
            {"description": "Sports shoes", "category": "Clothing", "line_total": "25200.00"},
            {"description": "Tournament entry", "category": "Entry", "line_total": "6000.00"},
            {"description": "Match balls and kit bag", "category": "Equipment", "line_total": "7500.00"},
            {"description": "Meals", "category": "Food", "line_total": "6750.00"},
        ],
    })

    assert [item.category for item in invoice.line_items] == [
        "Travel",
        "Travel",
        "Shopping & Retail",
        "Shopping & Retail",
        "Shopping & Retail",
        "Entertainment",
        "Shopping & Retail",
        "Groceries & Dining",
    ]
    assert invoice.category == "Shopping & Retail"
    line_schema = InvoiceExtraction.model_json_schema()["$defs"]["LineItem"]
    assert "category" in line_schema["required"]


def test_primary_invoice_category_is_derived_from_line_items():
    from app.ai import _validate_extraction_for_review

    result = _validate_extraction_for_review({
        "category": "Transportation",
        "line_items": [
            {"description": "Flight", "category": "Travel", "line_total": "600.00"},
            {"description": "Hotel", "category": "Travel", "line_total": "400.00"},
        ],
    })

    assert result.category == "Travel"


def test_ai_duplicate_comparison_uses_parsed_invoice_content(monkeypatch):
    from app.ai import same_invoice_content

    captured = {}

    async def fake_chat(messages, *, json_mode=False):
        captured["messages"] = messages
        captured["json_mode"] = json_mode
        return '{"same_invoice":false}'

    monkeypatch.setattr("app.ai._chat", fake_chat)
    first = InvoiceExtraction.model_validate({
        "invoice_number": "A-1",
        "seller_name": "Shop",
        "total": "25.00",
        "line_items": [{"description": "Tea", "category": "Groceries & Dining", "line_total": "25.00"}],
    })
    second = InvoiceExtraction.model_validate({
        "invoice_number": "A-1",
        "seller_name": "Shop",
        "total": "25.00",
        "line_items": [{"description": "Coffee", "category": "Groceries & Dining", "line_total": "25.00"}],
    })

    assert not asyncio.run(same_invoice_content(first, second))
    assert captured["json_mode"] is True
    prompt = captured["messages"][0]["content"]
    assert "matching filenames, sellers, dates, or totals alone are not sufficient" in prompt
    assert "Coffee" in captured["messages"][1]["content"]


def test_overview_groups_line_item_categories_and_preserves_legacy_invoice_totals():
    from app import main

    class FakeDatabase:
        def scalar(self, _query):
            return 0

        def execute(self, query):
            statement = str(query.compile(dialect=postgresql.dialect()))
            if "sum(coalesce(invoice_items.line_total" in statement:
                assert "GROUP BY invoices.id, invoice_items.category, invoices.category, invoices.currency, invoices.total" in statement
                assert "invoice_items.taxable_amount" in statement
                assert "invoice_items.quantity * invoice_items.unit_price" in statement
                discounted_invoice_id = uuid4()
                return SimpleNamespace(all=lambda: [
                    (uuid4(), "Transportation", "INR", Decimal("7200.00"), 1, Decimal("7200.00")),
                    (uuid4(), "Travel", "INR", Decimal("40200.00"), 2, Decimal("40200.00")),
                    (uuid4(), "Shopping & Retail", "INR", Decimal("43950.00"), 3, Decimal("43950.00")),
                    (uuid4(), "Groceries & Dining", "INR", Decimal("6750.00"), 1, Decimal("6750.00")),
                    (discounted_invoice_id, "Travel", "INR", Decimal("100.00"), 1, Decimal("135.00")),
                    (discounted_invoice_id, "Shopping & Retail", "INR", Decimal("50.00"), 1, Decimal("135.00")),
                ])
            if "invoices.seller_name" in statement:
                return SimpleNamespace(all=lambda: [])
            if "GROUP BY invoices.category, invoices.currency" in statement:
                assert "coalesce(invoice_items.line_total" in statement
                return SimpleNamespace(all=lambda: [("Other", "INR", Decimal("2500.00"), 1)])
            return SimpleNamespace(all=lambda: [("INR", Decimal("62600.00"))])

    result = main.overview(
        SimpleNamespace(id=uuid4(), preferred_currency="INR"),
        FakeDatabase(),
    )

    totals = {item["category"]: item["total"] for item in result["category_totals"]}
    assert totals == {
        "Transportation": "7200.00",
        "Travel": "40290.00",
        "Shopping & Retail": "43995.00",
        "Groceries & Dining": "6750.00",
        "Other": "2500.00",
    }


def test_invoice_schema_flags_total_discrepancy_without_replacing_extracted_value():
    invoice = InvoiceExtraction.model_validate({
        "currency": "inr", "taxable_value": "100.00", "cgst": "9.00",
        "sgst": "9.00", "total": "125.00",
    })
    assert invoice.total == Decimal("125.00")
    assert any("differ from the invoice total" in warning for warning in invoice.warnings)


def test_invoice_schema_preserves_missing_fields_as_none():
    invoice = InvoiceExtraction.model_validate({"document_type": "invoice"})
    assert invoice.invoice_number is None
    assert invoice.total is None
    assert invoice.line_items == []


def test_date_period_includes_boundaries():
    from datetime import date
    assert is_in_period(date(2026, 3, 1), date(2026, 3, 1), date(2026, 3, 31))
    assert not is_in_period(None, date(2026, 3, 1), date(2026, 3, 31))


def test_spending_over_time_groups_custom_date_range_by_month():
    from datetime import date

    rows = [
        (date(2026, 3, 12), Decimal("20.00")),
        (date(2026, 3, 31), Decimal("10.00")),
        (date(2026, 4, 1), Decimal("45.00")),
    ]

    class FakeDatabase:
        statement = None

        def execute(self, _query):
            self.statement = str(_query)
            return SimpleNamespace(all=lambda: rows)

    database = FakeDatabase()
    result = spending_over_time(
        SimpleNamespace(id=uuid4()),
        database,
        from_date=date(2026, 3, 1),
        to_date=date(2026, 4, 15),
    )
    assert result["monthly"] == [
        {"month": "Mar 2026", "total": "30.00"},
        {"month": "Apr 2026", "total": "45.00"},
    ]
    assert "invoices.invoice_date" in database.statement
    assert "invoices.created_at" not in database.statement


def test_spending_over_time_rejects_incomplete_custom_date_range():
    from datetime import date

    with pytest.raises(HTTPException, match="Both from_date and to_date are required"):
        spending_over_time(
            SimpleNamespace(id=uuid4()),
            SimpleNamespace(),
            from_date=date(2026, 3, 1),
        )


def test_duplicate_detection_normalizes_invoice_number_and_gstin():
    from datetime import date

    extraction = InvoiceExtraction.model_validate({
        "invoice_number": "INV- 001", "invoice_date": date(2026, 3, 1),
        "seller_gstin": "27ABCDE1234F1Z5", "total": "118.00",
    })
    existing = Invoice(
        invoice_number="inv001", invoice_date=date(2026, 3, 1),
        seller_gstin="27abcde1234f1z5", total=Decimal("118.00"),
    )
    assert has_duplicate_invoice(extraction, [existing])


def test_duplicate_detection_does_not_match_without_seller_identity():
    from datetime import date

    extraction = InvoiceExtraction.model_validate({
        "invoice_number": "123", "invoice_date": "2026-03-01", "total": "20.00",
    })
    existing = Invoice(invoice_number="123", invoice_date=date(2026, 3, 1), total=Decimal("20.00"))
    assert not has_duplicate_invoice(extraction, [existing])


def test_upload_queues_same_name_file_for_content_comparison(monkeypatch, tmp_path):
    from app import main

    user = SimpleNamespace(id=uuid4())
    file = SimpleNamespace(
        filename="invoice.pdf",
        read=lambda _limit: asyncio.sleep(0, result=b"%PDF-1.7 content"),
    )

    class FakeDatabase:
        def __init__(self):
            self.document = None

        def scalar(self, _query):
            return None

        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [])

        def add(self, document):
            self.document = document

        def commit(self):
            pass

    monkeypatch.setattr(main.settings, "temp_upload_dir", tmp_path)
    monkeypatch.setattr(main, "document_out", lambda document: {"status": document.status})
    database = FakeDatabase()

    response = asyncio.run(upload_document(user, database, file))

    assert response == {"status": "queued"}
    assert database.document.filename == "invoice.pdf"


def test_manual_expense_is_saved_with_a_categorized_line_item():
    from app.main import create_expense

    user = SimpleNamespace(id=uuid4())
    payload = InvoiceExtraction.model_validate({
        "document_type": "other",
        "invoice_date": "2026-10-14",
        "seller_name": "Corner Shop",
        "place_of_supply": "Bengaluru",
        "currency": "INR",
        "total": "125.50",
        "line_items": [{
            "description": "Household supplies",
            "category": "Shopping & Retail",
            "line_total": "125.50",
        }],
    })

    class FakeDatabase:
        invoice = None

        def add(self, invoice):
            self.invoice = invoice

        def commit(self):
            self.invoice.id = uuid4()

    database = FakeDatabase()
    response = create_expense(payload, user, database)

    assert response["status"] == "confirmed"
    assert database.invoice.seller_name == "Corner Shop"
    assert database.invoice.items[0].category == "Shopping & Retail"
    assert database.invoice.items[0].line_total == Decimal("125.50")


def test_document_status_includes_error_code_for_polling():
    document = SimpleNamespace(
        id=uuid4(),
        filename="invoice.pdf",
        status="failed",
        stage="Duplicate invoice detected",
        created_at=date(2026, 3, 1),
        error_code="DUPLICATE_INVOICE",
        error_message="This invoice already exists.",
    )
    assert document_out(document)["error_code"] == "DUPLICATE_INVOICE"


def test_document_details_reads_saved_invoice_and_items_by_document_and_user(monkeypatch):
    from app import main

    document_id, user_id = uuid4(), uuid4()
    document = SimpleNamespace(id=document_id, extraction=None)
    invoice = Invoice(
        id=uuid4(),
        user_id=user_id,
        document_id=document_id,
        total=Decimal("45.00"),
        currency="INR",
        seller_name="Corner Shop",
        validation_warnings=[],
        items=[InvoiceItem(
            description="Tea",
            category="Groceries & Dining",
            quantity=Decimal("2"),
            unit_price=Decimal("22.50"),
            line_total=Decimal("45.00"),
        )],
    )

    class FakeDatabase:
        def scalar(self, query):
            statement = str(query.compile(dialect=postgresql.dialect()))
            assert "invoices.document_id" in statement
            assert "invoices.user_id" in statement
            return invoice

    monkeypatch.setattr(main, "user_document", lambda _db, _user, _id: document)
    details = document_details(document_id, SimpleNamespace(id=user_id), FakeDatabase())

    assert details["expense_saved"] is True
    assert details["seller_name"] == "Corner Shop"
    assert details["total"] == "45.00"
    assert details["line_items"][0]["description"] == "Tea"
    assert details["line_items"][0]["category"] == "Groceries & Dining"
    assert details["line_items"][0]["line_total"] == "45.00"


def test_document_details_returns_pending_extraction_without_claiming_expense_saved(monkeypatch):
    from app import main

    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        extraction={"total": "123.45", "line_items": [{"description": "Tea", "line_total": "123.45"}]},
    )
    monkeypatch.setattr(main, "user_document", lambda _db, _user, _id: document)
    details = document_details(document_id, SimpleNamespace(id=uuid4()), SimpleNamespace(scalar=lambda _query: None))

    assert details["expense_saved"] is False
    assert details["total"] == "123.45"
    assert details["line_items"][0]["description"] == "Tea"


def test_document_details_reports_missing_extraction_and_invoice(monkeypatch):
    from app import main

    document_id = uuid4()
    document = SimpleNamespace(id=document_id, extraction=None)
    monkeypatch.setattr(main, "user_document", lambda _db, _user, _id: document)

    with pytest.raises(HTTPException, match="No extracted expense details") as error:
        document_details(document_id, SimpleNamespace(id=uuid4()), SimpleNamespace(scalar=lambda _query: None))

    assert error.value.status_code == 404


def test_upload_rejects_file_with_existing_fingerprint():
    user = SimpleNamespace(id=uuid4())
    file = SimpleNamespace(
        filename="invoice.pdf",
        read=lambda _limit: asyncio.sleep(0, result=b"%PDF-1.7 duplicate"),
    )
    database = SimpleNamespace(scalar=lambda _query: "already-stored.pdf")

    with pytest.raises(HTTPException, match="This file matches existing upload: already-stored.pdf") as error:
        asyncio.run(upload_document(user, database, file))

    assert error.value.status_code == 409
    assert error.value.detail.endswith("already-stored.pdf.")


def test_confirm_document_blocks_duplicate_invoice(monkeypatch):
    from app import main

    user = SimpleNamespace(id=uuid4())
    document = SimpleNamespace(id=uuid4(), status="review")
    existing = Invoice(
        invoice_number="INV-001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("20.00"),
        seller_name="Example Seller",
    )
    database = SimpleNamespace(
        scalars=lambda _query: SimpleNamespace(all=lambda: [existing]),
    )
    payload = InvoiceExtraction.model_validate({
        "invoice_number": "INV001",
        "invoice_date": "2026-03-01",
        "total": "20.00",
        "seller_name": "Example Seller",
    })
    monkeypatch.setattr(main, "user_document", lambda _db, _user, _id: document)

    with pytest.raises(HTTPException, match="This invoice already exists") as error:
        confirm_document(document.id, payload, user, database)

    assert error.value.status_code == 409


def test_confirm_document_allows_same_name_file_after_ai_found_different_content(monkeypatch):
    from app import main

    user = SimpleNamespace(id=uuid4())
    document = SimpleNamespace(
        id=uuid4(),
        status="review",
        allow_duplicate_invoice=True,
        temp_path=None,
    )
    payload = InvoiceExtraction.model_validate({
        "invoice_number": "INV001",
        "invoice_date": "2026-03-01",
        "total": "20.00",
        "seller_name": "Example Seller",
    })
    existing = Invoice(
        invoice_number="INV-001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("20.00"),
        seller_name="Example Seller",
    )

    class FakeDatabase:
        invoice = None

        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [existing])

        def add(self, invoice):
            self.invoice = invoice

        def commit(self):
            self.invoice.id = uuid4()

    monkeypatch.setattr(main, "user_document", lambda _db, _user, _id: document)

    database = FakeDatabase()
    result = confirm_document(document.id, payload, user, database)

    assert result["status"] == "confirmed"
    assert database.invoice.seller_name == "Example Seller"


def test_worker_marks_matching_invoice_as_duplicate(monkeypatch, tmp_path):
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        filename="invoice.pdf",
        mime_type="application/pdf",
        status="processing",
        temp_path=str(tmp_path / "duplicate.pdf"),
    )
    source = tmp_path / "duplicate.pdf"
    source.write_bytes(b"%PDF-1.7")
    existing = Invoice(
        document_id=uuid4(),
        invoice_number="INV-001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("20.00"),
        seller_name="Example Seller",
    )

    class FakeSession:
        def get(self, _model, _id):
            return document

        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [existing])

        def scalar(self, _query):
            return "original-invoice.pdf"

        def commit(self):
            pass

        def close(self):
            pass

    async def extract_duplicate(_text):
        return InvoiceExtraction.model_validate({
            "invoice_number": "INV001",
            "invoice_date": "2026-03-01",
            "total": "20.00",
            "seller_name": "Example Seller",
        })

    monkeypatch.setattr(worker, "SessionLocal", FakeSession)
    monkeypatch.setattr(worker, "extract_text", lambda _path, _mime: "Readable invoice content")
    monkeypatch.setattr(worker, "extract_invoice", extract_duplicate)

    worker.process_document(str(document.id))

    assert document.status == "failed"
    assert document.error_code == "DUPLICATE_INVOICE"
    assert "original-invoice.pdf" in document.error_message
    assert document.temp_path is None
    assert not source.exists()


def test_worker_marks_duplicate_when_format_difference_was_approved(monkeypatch, tmp_path):
    existing = Invoice(
        invoice_number="INV-001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("20.00"),
        seller_name="Example Seller",
    )
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        mime_type="image/png",
        allow_duplicate_invoice=True,
        status="processing",
        temp_path=str(tmp_path / "approved.png"),
    )
    source = tmp_path / "approved.png"
    source.write_bytes(b"\x89PNG")

    class FakeSession:
        def get(self, _model, _id):
            return document

        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [existing])

        def commit(self):
            pass

        def close(self):
            pass

    async def extract_duplicate(_text):
        return InvoiceExtraction.model_validate({
            "invoice_number": "INV001",
            "invoice_date": "2026-03-01",
            "total": "20.00",
            "seller_name": "Example Seller",
        })

    monkeypatch.setattr(worker, "SessionLocal", FakeSession)
    monkeypatch.setattr(worker, "extract_text", lambda _path, _mime: "Readable invoice content")
    monkeypatch.setattr(worker, "extract_invoice", extract_duplicate)

    worker.process_document(str(document.id))

    assert document.status == "failed"
    assert document.error_code == "DUPLICATE_INVOICE"
    assert document.temp_path is None
    assert not source.exists()


@pytest.mark.parametrize(
    ("same_content", "expected_status"),
    [(True, "failed"), (False, "review")],
)
def test_worker_uses_ai_to_resolve_same_name_content(
    monkeypatch, tmp_path, same_content, expected_status
):
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        filename="invoice.pdf",
        mime_type="application/pdf",
        status="processing",
        temp_path=str(tmp_path / "invoice.pdf"),
    )
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"%PDF-1.7")
    existing = Invoice(
        document_id=uuid4(),
        user_id=document.user_id,
        invoice_number="INV-001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("20.00"),
        seller_name="Example Seller",
        items=[InvoiceItem(
            description="A different line item",
            category="Shopping & Retail",
            line_total=Decimal("20.00"),
        )],
    )

    class FakeSession:
        def get(self, _model, _id):
            return document

        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [existing])

        def scalar(self, _query):
            return "previous-invoice.pdf"

        def commit(self):
            pass

        def close(self):
            pass

    async def extract_invoice(_text):
        return InvoiceExtraction.model_validate({
            "invoice_number": "INV-001",
            "invoice_date": "2026-03-01",
            "total": "20.00",
            "seller_name": "Example Seller",
            "line_items": [{
                "description": "Different purchase",
                "category": "Shopping & Retail",
                "line_total": "20.00",
            }],
        })

    async def compare_content(_first, _second):
        return same_content

    monkeypatch.setattr(worker, "SessionLocal", FakeSession)
    monkeypatch.setattr(worker, "extract_text", lambda _path, _mime: "Readable invoice content")
    monkeypatch.setattr(worker, "extract_invoice", extract_invoice)
    monkeypatch.setattr(worker, "same_invoice_content", compare_content)

    worker.process_document(str(document.id))

    assert document.status == expected_status
    assert document.error_code == ("DUPLICATE_INVOICE" if same_content else None)
    if same_content:
        assert "previous-invoice.pdf" in document.error_message
    assert getattr(document, "allow_duplicate_invoice", False) is (not same_content)
    assert source.exists() is (not same_content)


def test_invoice_database_values_exclude_schema_only_fields():
    payload = InvoiceExtraction.model_validate({
        "document_type": "invoice", "category": "Business", "seller_name": "Shop", "total": "25.00",
        "line_items": [{"description": "Item", "line_total": "25.00"}],
    })
    values = invoice_values(payload)
    assert values["seller_name"] == "Shop"
    assert values["total"] == Decimal("25.00")
    assert values["category"] == "Business"
    assert "document_type" not in values
    assert "line_items" not in values
    assert "warnings" not in values


def test_invalid_ai_expense_category_is_reviewed_as_other():
    from app.ai import _validate_extraction_for_review

    result = _validate_extraction_for_review({"category": "Luxury spaceship"})

    assert result.category == "Other"
    assert any("Category could not be read reliably" in warning for warning in result.warnings)


def test_ai_classifies_each_legacy_expense_from_merchant_and_items(monkeypatch):
    from app.ai import classify_expense_categories

    async def fake_chat(messages, *, json_mode=False):
        assert json_mode
        prompt = messages[0]["content"]
        assert "untrusted data" in prompt
        return '{"categories":[{"id":"invoice-1","category":"Groceries & Dining"}]}'

    monkeypatch.setattr("app.ai._chat", fake_chat)
    result = asyncio.run(classify_expense_categories([
        {"id": "invoice-1", "merchant": "Fresh Market", "items": ["Vegetables"]},
    ]))

    assert result == {"invoice-1": "Groceries & Dining"}


def test_ai_rejects_incomplete_expense_category_results(monkeypatch):
    from app.ai import classify_expense_categories

    async def fake_chat(_messages, *, json_mode=False):
        return '{"categories":[]}'

    monkeypatch.setattr("app.ai._chat", fake_chat)
    with pytest.raises(HTTPException) as error:
        asyncio.run(classify_expense_categories([
            {"id": "invoice-1", "merchant": "Shop", "items": ["Item"]},
        ]))

    assert error.value.status_code == 502
    assert "every line item" in error.value.detail


def test_category_analysis_updates_individual_line_items(monkeypatch):
    from app import main

    user = SimpleNamespace(id=uuid4())
    invoice = Invoice(
        user_id=user.id,
        seller_name="Market",
        category=None,
        total=Decimal("60.00"),
        items=[InvoiceItem(description="Tea", category=None, line_total=Decimal("60.00"))],
    )
    line_item = invoice.items[0]

    class FakeDatabase:
        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [line_item])

        def scalar(self, _query):
            return 0

        def commit(self):
            pass

    async def classify(items):
        assert items == [{
            "id": "item_0",
            "merchant": "Market",
            "items": ["Tea"],
        }]
        return {"item_0": "Groceries & Dining"}

    monkeypatch.setattr(main, "classify_expense_categories", classify)
    response = asyncio.run(main.analyze_expense_categories(user, FakeDatabase()))

    assert response == {"categorized": 1, "remaining": 0}
    assert line_item.category == "Groceries & Dining"
    assert invoice.category is None


def test_text_pdf_extracts_selectable_text_without_ocr(tmp_path):
    path = tmp_path / "invoice.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Invoice INV-2026-04\nTotal INR 118.00")
        document.save(path)

    text = extract_text(path, "application/pdf")

    assert "INV-2026-04" in text
    assert "118.00" in text


def test_pdf_preview_renders_requested_page_and_reports_page_count(tmp_path):
    path = tmp_path / "invoice.pdf"
    with fitz.open() as document:
        for index in range(2):
            page = document.new_page()
            page.insert_text((72, 72), f"Invoice page {index + 1}")
        document.save(path)

    image, page_count, width, height = render_pdf_page(path, 2)

    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert page_count == 2
    assert width > 0
    assert height > 0


def test_pdf_preview_rejects_page_outside_document(tmp_path):
    path = tmp_path / "invoice.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(path)

    with pytest.raises(HTTPException) as error:
        render_pdf_page(path, 2)

    assert error.value.status_code == 416


def test_image_ocr_reports_missing_tesseract(monkeypatch, tmp_path):
    path = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(path)

    def missing_tesseract(image: Image.Image, *, config: str, timeout: int):
        assert image.mode == "L"
        assert config == "--psm 4"
        assert timeout == 45
        raise TesseractNotFoundError()

    monkeypatch.setattr("app.documents.pytesseract.image_to_string", missing_tesseract)

    with pytest.raises(HTTPException) as error:
        extract_text(path, "image/png")

    assert error.value.status_code == 503
    assert "TESSERACT_CMD" in error.value.detail
    assert "restart the worker" in error.value.detail


def test_image_ocr_reports_tesseract_read_failure(monkeypatch, tmp_path):
    path = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(path)

    def failed_ocr(image: Image.Image, *, config: str, timeout: int):
        assert image.mode == "L"
        assert config == "--psm 4"
        assert timeout == 45
        raise TesseractError(1, "image processing failed")

    monkeypatch.setattr("app.documents.pytesseract.image_to_string", failed_ocr)

    with pytest.raises(HTTPException) as error:
        extract_text(path, "image/png")

    assert error.value.status_code == 422
    assert "Tesseract could not read this image" in error.value.detail


def test_image_ocr_uses_receipt_table_layout(monkeypatch, tmp_path):
    path = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), "white").save(path)
    observed = {}

    def read_receipt(image: Image.Image, *, config: str, timeout: int):
        observed["image_mode"] = image.mode
        observed["size"] = image.size
        observed["config"] = config
        observed["timeout"] = timeout
        return "Item Qty Rate Amount\nMilk 1 62.00 62.00"

    monkeypatch.setattr("app.documents.pytesseract.image_to_string", read_receipt)

    assert extract_text(path, "image/png") == "Item Qty Rate Amount\nMilk 1 62.00 62.00"
    assert observed == {"image_mode": "L", "size": (40, 40), "config": "--psm 4", "timeout": 45}


def test_pdf_preview_recovers_upload_path_when_database_path_is_missing(monkeypatch, tmp_path):
    document_id = uuid4()
    expected_path = tmp_path / f"{document_id}.pdf"
    expected_path.write_bytes(b"%PDF-test")
    monkeypatch.setattr("app.main.settings.temp_upload_dir", tmp_path)
    document = SimpleNamespace(id=document_id, mime_type="application/pdf", temp_path=None)

    assert document_preview_path(document) == expected_path


def test_ai_configuration_failure_is_explicit(monkeypatch):
    from app.ai import _api_key
    from app.core.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "groq_api_key", None)
    with pytest.raises(HTTPException) as error:
        _api_key()
    assert error.value.status_code == 503
    assert "GROQ_API_KEY" in error.value.detail
    monkeypatch.setattr(settings, "groq_api_key", SecretStr("test"))


def test_invalid_optional_invoice_fields_are_left_for_review():
    from app.ai import _validate_extraction_for_review

    result = _validate_extraction_for_review({
        "invoice_number": "INV-15",
        "invoice_date": "not a date",
        "total": "not an amount",
        "currency": "RUPEES ONLY",
        "line_items": [{"description": "Usable item", "line_total": "125.00"}],
    })

    assert result.invoice_number == "INV-15"
    assert result.total is None
    assert result.invoice_date is None
    assert result.currency == "XXX"
    assert result.line_items[0].description == "Usable item"
    assert len(result.warnings) >= 3


def test_invalid_invoice_line_is_omitted_with_a_review_warning():
    from app.ai import _validate_extraction_for_review

    result = _validate_extraction_for_review({
        "total": "125.00",
        "line_items": [
            {"description": "Good item", "line_total": "125.00"},
            {"description": "", "line_total": "bad"},
            {"description": "Another good item", "line_total": "0.00"},
        ],
    })

    assert [item.description for item in result.line_items] == ["Good item", "Another good item"]
    assert any("could not be checked and was omitted" in warning for warning in result.warnings)


def test_groq_invoice_amounts_with_rupee_grouping_are_normalized():
    from app.ai import _validate_extraction_for_review

    result = _validate_extraction_for_review({
        "currency": "₹",
        "subtotal": "₹ 1,23,456.78",
        "total": "Rs. 1,23,456.78",
        "invoice_date": "October 13, 2026",
        "line_items": [{"description": "Service", "line_total": "₹12,345.00"}],
    })

    assert result.currency == "INR"
    assert result.subtotal == Decimal("123456.78")
    assert result.total == Decimal("123456.78")
    assert result.invoice_date.isoformat() == "2026-10-13"
    assert result.line_items[0].line_total == Decimal("12345.00")


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ("Grand Total: ₹ 1,23,456.78", "123456.78"),
        ("Amount Payable INR 245.00", "245.00"),
        ("TOTAL 875", "875"),
    ],
)
def test_missing_invoice_total_is_recovered_from_explicit_ocr_total_row(row, expected):
    from app.ai import _recover_missing_invoice_total

    data = {"total": None}
    _recover_missing_invoice_total(data, f"Description\nItem total 10.00\n{row}")

    assert data["total"] == expected


def test_invoice_total_recovery_preserves_extracted_total():
    from app.ai import _recover_missing_invoice_total

    data = {"total": "125.50"}
    _recover_missing_invoice_total(data, "Grand Total: 200.00")

    assert data["total"] == "125.50"


def test_missing_or_invalid_invoice_total_is_recovered_when_ocr_has_labeled_total():
    from app.ai import _recover_missing_invoice_total

    for current_total in ("", "not an amount"):
        data = {"total": current_total}
        _recover_missing_invoice_total(data, "Grand Total: INR 200.00")
        assert data["total"] == "200.00"


def test_postgres_worker_claims_documents_with_skip_locked(monkeypatch):
    document = SimpleNamespace(
        id=uuid4(),
        status="queued",
        stage="Upload accepted",
        temp_path=None,
        updated_at=None,
        error_code="old-error",
        error_message="old message",
    )

    class FakeSession:
        statement = None
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def scalar(self, statement):
            self.statement = statement
            return document

        def commit(self):
            self.committed = True

    session = FakeSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    claimed_id = worker.claim_next_document()
    statement = str(session.statement.compile(dialect=postgresql.dialect()))

    assert claimed_id == str(document.id)
    assert document.status == "processing"
    assert document.stage == "Starting document processing"
    assert document.error_code is None
    assert document.error_message is None
    assert session.committed
    assert "FOR UPDATE SKIP LOCKED" in statement


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("postgresql://db.example.test/app", "postgresql+psycopg://db.example.test/app"),
        ("postgres://db.example.test/app", "postgresql+psycopg://db.example.test/app"),
        ("postgresql+psycopg://db.example.test/app", "postgresql+psycopg://db.example.test/app"),
    ],
)
def test_database_url_uses_installed_psycopg_driver(database_url, expected):
    configured = Settings(auth_secret="test-secret-that-is-long-enough-123456", database_url=database_url)
    assert configured.database_url == expected
