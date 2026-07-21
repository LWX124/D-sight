import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FundArbFund(Base):
    """基金配置（seed 导入）。tracking_symbol/sina_symbol 直接存行情源代码。"""

    __tablename__ = "fund_arb_funds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    fund_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # gold_oil / qdii_us_eu / qdii_japan / qdii_asia / domestic_lof / silver / cash_bond
    category: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    sina_symbol: Mapped[str] = mapped_column(String(24), nullable=False)   # 场内行情代码 sh501018/sz161129
    tracking_symbol: Mapped[str] = mapped_column(String(32), nullable=False)  # 跟踪标的行情代码
    tracking_type: Mapped[str] = mapped_column(String(16), nullable=False)  # index / future / us_etf
    currency: Mapped[str | None] = mapped_column(String(8))  # USD/HKD/JPY，国内基金为 NULL
    rate_type: Mapped[str] = mapped_column(String(8), nullable=False, default="mid")  # mid / spot
    valuation_method: Mapped[str] = mapped_column(String(16), nullable=False)  # index / silver_future / bond_growth
    nav_field: Mapped[str] = mapped_column(String(8), nullable=False, default="dwjz")  # dwjz / ljjz（货基用累计）
    pos_ratio_default: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    approx: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 近似估值标记（篮子基金）
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundArbDaily(Base):
    """日史宽表。行的 date 即净值日期：nav 为该日官方净值（公布后回填），
    est_nav_close 为该日收盘时我方估值，二者同日对账 → valuation_error。"""

    __tablename__ = "fund_arb_daily"
    __table_args__ = (UniqueConstraint("date", "fund_code", name="uq_fund_arb_daily_date_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    fund_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    price: Mapped[float | None] = mapped_column(Float)
    price_pct: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)  # 成交额（元）
    nav: Mapped[float | None] = mapped_column(Float)
    est_nav_close: Mapped[float | None] = mapped_column(Float)
    premium: Mapped[float | None] = mapped_column(Float)  # 收盘溢价（%）
    valuation_error: Mapped[float | None] = mapped_column(Float)  # (est/nav−1)×100，盘后回填
    purchase_status: Mapped[str | None] = mapped_column(String(16))
    redemption_status: Mapped[str | None] = mapped_column(String(16))
    purchase_limit: Mapped[str | None] = mapped_column(String(32))  # 日累计限额原文，如 "1000"
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundArbFactor(Base):
    """回归校准因子（盘后更新）。"""

    __tablename__ = "fund_arb_factors"
    __table_args__ = (UniqueConstraint("fund_code", "date", name="uq_fund_arb_factor_code_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    position_beta: Mapped[float] = mapped_column(Float, nullable=False)
    r_squared: Mapped[float] = mapped_column(Float, nullable=False)
    sample_days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundArbTrackingDaily(Base):
    """跟踪标的日收盘（含汇率中间价：USDCNY_MID/HKDCNY_MID/JPYCNY_MID）。"""

    __tablename__ = "fund_arb_tracking_daily"
    __table_args__ = (UniqueConstraint("date", "symbol", name="uq_fund_arb_tracking_date_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
