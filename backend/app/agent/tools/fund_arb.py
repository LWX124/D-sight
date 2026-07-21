from langchain_core.tools import tool

from app.fund_arb.snapshot import get_store

_CATEGORY_NAMES = {
    "gold_oil": "黄金原油", "qdii_us_eu": "QDII欧美", "qdii_japan": "QDII日本",
    "qdii_asia": "QDII亚洲", "domestic_lof": "国内LOF", "silver": "白银",
    "cash_bond": "现金管理",
}


def make_fund_arb_query():
    @tool
    async def fund_arb_query(
        category: str = "",
        min_premium: float | None = None,
        max_premium: float | None = None,
        code: str = "",
    ) -> str:
        """查询基金套利看板的实时折溢价快照。category 可选：gold_oil/qdii_us_eu/
        qdii_japan/qdii_asia/domestic_lof/silver/cash_bond；min_premium/max_premium
        按溢价率（%）过滤（折价用负数，如 max_premium=-1 查折价超1%）；code 查单只基金。
        结果含估值误差与申购限额——判断套利机会是否可执行时必须看申购状态。"""
        try:
            rows = get_store().rows(category or None)
            if code:
                rows = [r for r in rows if r.fund_code == code]
            if min_premium is not None:
                rows = [r for r in rows if r.premium is not None and r.premium >= min_premium]
            if max_premium is not None:
                rows = [r for r in rows if r.premium is not None and r.premium <= max_premium]
            if not rows:
                return "（无符合条件的基金；可能是快照未就绪或条件过严）"
            lines = []
            for r in rows[:30]:
                prem = f"{r.premium:+.2f}%" if r.premium is not None else "—"
                est = f"{r.est_nav:.4f}" if r.est_nav is not None else "—"
                err = f"{r.err_5d:.2f}%" if r.err_5d is not None else "—"
                flags = ("[近似]" if r.approx else "") + ("[低置信]" if r.low_confidence else "")
                lines.append(
                    f"{r.fund_code} {r.fund_name}({_CATEGORY_NAMES.get(r.category, r.category)})"
                    f" 现价{r.price} 估值{est} 溢价{prem}{flags}"
                    f" 净值日{r.nav_date} 5日误差{err}"
                    f" 申购:{r.purchase_status or '—'}"
                    f"{'(限' + r.purchase_limit + ')' if r.purchase_limit else ''}"
                    f" 赎回:{r.redemption_status or '—'}"
                    f" [{'实时' if r.source == 'realtime' else '收盘'}]"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"（基金套利查询失败：{e}）"

    return fund_arb_query
