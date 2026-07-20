import datetime as dt

import pytest
import respx
from httpx import Response

from app.fund_arb.fetchers import (
    FakeQuoteFetcher,
    Quote,
    SinaQuoteFetcher,
    fetch_fx_mid,
    fetch_nav_history,
)

# 真实抓包 2026-07-20（字段下标已校准）
SINA_BODY = (
    'var hq_str_sz161129="原油基金,1.906,1.814,1.995,1.995,1.906,1.995,0.000,'
    '691601588,1349537980.809,8206584,1.995,25800,1.994,28200,1.993,416100,1.992,'
    '29900,1.991,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,2026-07-20,15:00:00,00";\n'
    'var hq_str_sh000300="沪深300,4575.6712,4529.0953,4598.3208,4628.7985,4521.1808,'
    '0,0,333116058,933403207741,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
    '2026-07-20,15:35:34,00,";\n'
    'var hq_str_gb_uso="油价ETF,123.9600,3.91,2026-07-20 20:04:52,4.6600,123.2000,'
    '124.8800,121.4500,154.0800,65.9850,5953761,7261625,0,0.00,--,0.00,0.00,0.00,'
    '0.00,0,0,123.8399,-0.12,-0.15,Jul 20 08:04AM EDT,Jul 17 04:00PM EDT,119.3000,'
    '794059,1,2026,734889466.9611,128.1000,121.1500,97928952.5151,125.3025,123.9900";\n'
    'var hq_str_nf_AG0="白银连续,150000,13480.000,13986.000,13386.000,13753.000,'
    '13751.000,13753.000,13753.000,13686.000,13587.000,2,2,210628.000,646870,沪,白银,'
    '2026-07-20,1,,,,,,,,,13686.032,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,'
    '0,0.000,0,0.000,0";\n'
    'var hq_str_fx_susdcny="20:04:37,6.7700000000,6.7720000000,6.7752000000,'
    '234.0000000000,6.7677000000,6.7768000000,6.7534000000,6.7710000000,在岸人民币,'
    '-0.0620,-0.0042,0.0234,此行情由新浪财经计算得出,0.0000,0.0000,,2026-07-20";\n'
    'var hq_str_int_nikkei="日经指数,44946.64,-408.35,-0.90";\n'
    'var hq_str_rt_hkHSI="HSI,恒生指数,24835.030,24562.240,25155.550,24756.360,'
    '25143.049,580.810,2.360,0.000,0.000,306413327.345,13668197465,0.000,0.000,'
    '28056.100,22518.000,2026/07/20,16:08:48,,,,,,";\n'
)


@pytest.mark.asyncio
async def test_fake_fetcher_returns_subset():
    f = FakeQuoteFetcher({"sz161129": Quote(symbol="sz161129", price=1.04, prev_close=1.02)})
    got = await f.fetch_quotes(["sz161129", "sh000300"])
    assert set(got) == {"sz161129"}


@pytest.mark.asyncio
@respx.mock
async def test_sina_parse_all_prefixes():
    respx.get(url__startswith="https://hq.sinajs.cn/").mock(
        return_value=Response(200, text=SINA_BODY)
    )
    f = SinaQuoteFetcher()
    got = await f.fetch_quotes([
        "sz161129", "sh000300", "gb_uso", "nf_AG0",
        "fx_susdcny", "int_nikkei", "rt_hkHSI",
    ])
    # A股基金
    assert got["sz161129"].price == pytest.approx(1.995)
    assert got["sz161129"].prev_close == pytest.approx(1.814)
    assert got["sz161129"].pct == pytest.approx((1.995 / 1.814 - 1) * 100, rel=1e-4)
    # 指数
    assert got["sh000300"].price == pytest.approx(4598.3208)
    assert got["sh000300"].prev_close == pytest.approx(4529.0953)
    # 美股
    assert got["gb_uso"].price == pytest.approx(123.96)
    assert got["gb_uso"].pct == pytest.approx(3.91)
    # 期货
    assert got["nf_AG0"].price == pytest.approx(13753.0)
    assert got["nf_AG0"].prev_settle == pytest.approx(13587.0)
    # 外汇
    assert got["fx_susdcny"].price == pytest.approx(6.77)
    # 国际指数
    assert got["int_nikkei"].price == pytest.approx(44946.64)
    assert got["int_nikkei"].pct == pytest.approx(-0.90)
    # 港股指数
    assert got["rt_hkHSI"].price == pytest.approx(25143.049)
    assert got["rt_hkHSI"].prev_close == pytest.approx(24562.240)
    assert got["rt_hkHSI"].pct == pytest.approx(2.36)


@pytest.mark.asyncio
@respx.mock
async def test_sina_malformed_line_isolated():
    body = (
        'var hq_str_sz161129="";\n'
        'var hq_str_sh000300="沪深300,4575.6712,4529.0953,4598.3208,4628.7985,4521.1808,'
        '0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-20,15:00:03,00,";\n'
    )
    respx.get(url__startswith="https://hq.sinajs.cn/").mock(
        return_value=Response(200, text=body)
    )
    got = await SinaQuoteFetcher().fetch_quotes(["sz161129", "sh000300"])
    assert "sz161129" not in got
    assert got["sh000300"].price == pytest.approx(4598.3208)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_nav_history():
    respx.get(url__startswith="https://api.fund.eastmoney.com/f10/lsjz").mock(
        return_value=Response(200, json={
            "Data": {"LSJZList": [
                {"FSRQ": "2026-07-17", "DWJZ": "1.0210", "LJJZ": "1.5210", "FHSP": ""},
                {"FSRQ": "2026-07-16", "DWJZ": "1.0150", "LJJZ": "1.5150",
                 "FHSP": "每份派现金0.0200元"},
            ]},
        })
    )
    recs = await fetch_nav_history("161129", count=10)
    assert recs[0].date == dt.date(2026, 7, 17)
    assert recs[0].nav == pytest.approx(1.021)
    assert recs[0].dividend is None
    assert recs[1].dividend == "每份派现金0.0200元"
    assert recs[1].acc_nav == pytest.approx(1.515)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_fx_mid():
    respx.get(url__startswith="https://www.chinamoney.com.cn/").mock(
        return_value=Response(200, json={"records": [
            {"vrtName": "USD/CNY", "price": "7.1650"},
            {"vrtName": "HKD/CNY", "price": "0.9180"},
            {"vrtName": "100JPY/CNY", "price": "4.8200"},
        ]})
    )
    mids = await fetch_fx_mid()
    assert mids["USDCNY_MID"] == pytest.approx(7.165)
    assert mids["JPYCNY_MID"] == pytest.approx(0.0482)
