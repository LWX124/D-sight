"""公司概况：名称、所属行业、上市日期、主营业务。

源：巨潮 `stock_profile_cninfo`（东财 `stock_individual_info_em` 走 push2 域，本环境被拦截）。
"""

from __future__ import annotations

from datetime import date, datetime

import akshare as ak
import pandas as pd

from .akshare_client import fetch_df
from .errors import DataIncomplete, MarketNotSupported
from .schemas import DataPoint, PointSet
from .symbols import CN_MARKET, normalize_cn_code

SOURCE_PROFILE = "akshare:stock_profile_cninfo"

_FIELD_MAP = {
    "公司名称": "identity_name",
    "A股简称": "identity_short_name",
    "所属行业": "identity_industry",
    "所属市场": "identity_exchange",
    "上市日期": "identity_listing_date",
    "主营业务": "identity_main_business",
}


def _to_iso(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    return str(value)


def get_profile(symbol: str, market: str = CN_MARKET) -> PointSet:
    """取公司概况。

    `as_of` 用抓取当日：概况类数据上游不提供更新时间，用报告期冒充会误导新鲜度判断。
    """
    if market != CN_MARKET:
        raise MarketNotSupported(market, "identity")
    code = normalize_cn_code(symbol)

    df = fetch_df(SOURCE_PROFILE, ak.stock_profile_cninfo, symbol=code)
    row = df.iloc[0]
    fetched_on = date.today()

    points: dict[str, DataPoint] = {}
    for column, key in _FIELD_MAP.items():
        if column not in df.columns or pd.isna(row[column]):
            continue
        value = _to_iso(row[column]) if column == "上市日期" else str(row[column]).strip()
        if not value:
            continue
        points[key] = DataPoint(
            key=key,
            value=value,
            as_of=fetched_on,
            source=SOURCE_PROFILE,
            warnings=("概况类数据上游无更新时间，as_of 为抓取日",),
        )

    if not points:
        raise DataIncomplete(SOURCE_PROFILE, sorted(_FIELD_MAP))

    # diagnosis 的 identity 块预期 identity_sector；巨潮只给一层行业分类，
    # 直接复用同一值并标注，而不是编一个更细的分类。
    industry = points.get("identity_industry")
    if industry:
        points["identity_sector"] = DataPoint(
            key="identity_sector",
            value=industry.value,
            as_of=industry.as_of,
            source=SOURCE_PROFILE,
            warnings=("上游仅一层行业分类，sector 与 industry 同值",),
        )

    return PointSet(symbol=code, points=points)
