"""一次性工具：读 arbTest lof_config.yaml 生成 funds.yaml 草稿。

用法：uv run python scripts/convert_arbtest_lof.py \
        /Users/weixi1/Documents/Study/arbTest/arbcore/config/lof_config.yaml \
        > app/fund_arb/seed_data/funds.yaml
输出为草稿，必须按 OVERRIDES 与校对清单人工核对后才能提交。
"""
import sys

import yaml

CATEGORY_MAP = {
    "黄金原油": "gold_oil", "QDII欧美": "qdii_us_eu", "QDII日本": "qdii_japan",
    "QDII亚洲": "qdii_asia", "国内LOF": "domestic_lof", "白银": "silver",
    "现金管理": "cash_bond",
}

OVERRIDES: dict[str, dict] = {
    "501018": {"tracking_symbol": "gb_uso", "tracking_type": "us_etf", "approx": True},
    "160723": {"tracking_symbol": "gb_uso", "tracking_type": "us_etf", "approx": True},
    "161129": {"tracking_symbol": "gb_uso", "tracking_type": "us_etf", "approx": True},
    "160719": {"tracking_symbol": "gb_gld", "tracking_type": "us_etf", "approx": True},
    "161226": {"tracking_symbol": "nf_AG0", "tracking_type": "future",
               "valuation_method": "silver_future"},
    "511880": {"valuation_method": "bond_growth", "nav_field": "ljjz", "tracking_symbol": "-"},
    "511360": {"valuation_method": "bond_growth", "tracking_symbol": "-"},
    "511520": {"valuation_method": "bond_growth", "tracking_symbol": "-"},
}

CURRENCY_BY_CATEGORY = {
    "gold_oil": "USD", "qdii_us_eu": "USD", "qdii_japan": "JPY", "qdii_asia": "HKD",
}


def sina_symbol(code: str) -> str:
    return ("sh" if code.startswith("5") else "sz") + code


def main(path: str) -> None:
    src = yaml.safe_load(open(path, encoding="utf-8"))
    out = []
    for f in src["funds"]:
        code = str(f["code"])
        category = CATEGORY_MAP.get(f.get("category", ""), None)
        if category is None:
            continue
        position = f.get("position") or 95.0
        entry = {
            "fund_code": code,
            "fund_name": f["name"],
            "category": category,
            "sina_symbol": sina_symbol(code),
            "tracking_symbol": str(f.get("related_index", "")),
            "tracking_type": "index",
            "currency": CURRENCY_BY_CATEGORY.get(category),
            "rate_type": "mid",
            "valuation_method": "index",
            "nav_field": "dwjz",
            "pos_ratio_default": round(position / 100.0, 4),
            "approx": False,
            "enabled": True,
        }
        entry.update(OVERRIDES.get(code, {}))
        out.append(entry)
    yaml.safe_dump({"funds": out}, sys.stdout, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    main(sys.argv[1])
