import datetime as dt

from pydantic import BaseModel


class DashboardRow(BaseModel):
    fund_code: str
    fund_name: str
    category: str
    price: float | None
    price_pct: float | None
    amount: float | None
    est_nav: float | None
    premium: float | None
    nav: float | None
    nav_date: dt.date | None
    err_5d: float | None
    low_confidence: bool
    approx: bool
    purchase_status: str | None
    redemption_status: str | None
    purchase_limit: str | None
    source: str


class DashboardOut(BaseModel):
    rows: list[DashboardRow]
    as_of: dt.datetime | None
    market_open: bool


class HistoryPoint(BaseModel):
    date: dt.date
    price: float | None
    nav: float | None
    premium: float | None
    valuation_error: float | None


class HistoryOut(BaseModel):
    points: list[HistoryPoint]
