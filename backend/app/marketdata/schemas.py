"""marketdata 返回契约。

硬约束：任何对外返回的数值都必须携带 `as_of`（数据本身的时间）与 `source`
（接口级来源标识），二者缺一即视为无效数据，直接抛异常而非补默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Union

Number = Union[int, float]


@dataclass(frozen=True)
class DataPoint:
    """单个带溯源的取值。"""

    key: str
    value: Optional[Union[Number, str]]
    as_of: Union[date, datetime]
    source: str
    unit: Optional[str] = None
    period: Optional[str] = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError(f"DataPoint({self.key}) 缺少 source")
        if self.as_of is None:
            raise ValueError(f"DataPoint({self.key}) 缺少 as_of")

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "as_of": self.as_of.isoformat(),
            "source": self.source,
            "unit": self.unit,
            "period": self.period,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class Bar:
    """单根日线（前复权）。"""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None
    turnover: Optional[float] = None


@dataclass(frozen=True)
class DailyBars:
    """日线序列，按日期升序。"""

    symbol: str
    bars: list[Bar]
    source: str

    @property
    def as_of(self) -> date:
        return self.bars[-1].date

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def highs(self) -> list[float]:
        return [b.high for b in self.bars]

    @property
    def lows(self) -> list[float]:
        return [b.low for b in self.bars]

    @property
    def volumes(self) -> list[float]:
        return [b.volume for b in self.bars]

    def __len__(self) -> int:
        return len(self.bars)


@dataclass(frozen=True)
class PointSet:
    """一组同源取值（如一次财报解析出的多项指标）。"""

    symbol: str
    points: dict[str, DataPoint] = field(default_factory=dict)

    def get(self, key: str) -> Optional[DataPoint]:
        return self.points.get(key)

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self.points.items()}
