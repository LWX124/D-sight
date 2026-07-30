---
name: holder-structure-scan
description: Read A-share shareholder structure and chip concentration with the Pandadata
  get_holder_count, get_top_holders and get_share_float interfaces — tracking holder-count
  trend (户数) and average holding per account, top-holder concentration (前十大合计占比,
  flow vs total), and free-float share (自由流通占比), to see whether chips are concentrating
  or dispersing over successive disclosure periods, for a single name or a small watchlist.
  Use when the user asks for 股东户数, 户数变化, 筹码集中度, 户均持股, 前十大股东占比, 股东结构, 筹码分散,
  股东户数趋势, or an A-share shareholder-structure scan.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-holder-structure-scan
  repository_url: https://github.com/quantskills/skill-holder-structure-scan
  project_type: skill
  collection: holder-structure-scan
  creator: abgyjaguo
  maintainer: abgyjaguo
quantSkills:
  project_type: skill
  category: monitor
  tags:
  - a-share
  - shareholder-structure
  - chip-concentration
  - holder-count
  - top-holders
  - pandadata
  platforms:
  - claude-code
  - codex
  - hermes
  - openclaw
  - cursor
  status: draft
  validation_level: runnable
  maintainer_type: community
  summary_zh: A股股东户数与筹码集中度扫描：跟踪股东户数趋势与户均持股、前十大股东合计占比(流通/总股本口径)、自由流通占比，判断多个披露期内筹码是在集中还是分散，支持单票与小自选清单，明确披露频率与滞后。
  summary_en: A-share shareholder-structure and chip-concentration scan tracking holder-count
    trend and average holding per account, top-holder concentration (flow vs total),
    and free-float share, to see whether chips are concentrating or dispersing across
    disclosure periods, for a single name or a small watchlist.
  license: GPL-3.0-only
  requires:
  - skill-pandadata-api
---

# Holder Structure Scan

Use this skill to **read A-share shareholder structure and chip concentration**: for a single name or a small watchlist, track the **holder-count (户数) trend** and **average holding per account (户均持股)**, the **top-holder concentration** (前十大股东合计占比, distinguishing 流通口径 from 总股本口径), and the **free-float share** (自由流通占比), then judge whether chips are **concentrating** or **dispersing** across successive disclosure periods. Prefer Pandadata as the data source, keep every figure traceable to `get_holder_count` / `get_top_holders` / `get_share_float` and a disclosure date, and never invent counts, ratios, or trends.

## Scope And Positioning (read first to avoid overlap)

This skill is the **shareholder-structure / chip-concentration** view. It is deliberately distinct from its siblings:

- Unlike `stock-screener` (natural-language cross-market *filter* that may use holder count as one condition): this skill does not filter a universe — it reads **structure over time** for a chosen name/watchlist (户数 trend, concentration trend, free-float), building a per-name diagnostic. If the user wants to screen the whole market by a holder condition, hand off to `stock-screener`.
- Unlike `smart-money-profiler` (龙虎榜 / northbound / margin daily "smart money" seat flow): that reads *trading* seats day by day; this skill reads the **registered ownership** structure disclosed quarterly/periodically. Different cadence, different question.
- Unlike `event-risk-alert` (per-name watchlist risk — unlocks/pledges/reductions as *events*): concentration change is a *structural* read, not a filing-level alert. A reduction event surfaced there will often show up here as a 户数/占比 shift; cross-check, but the structural view lives here.
- Unlike `a-share-stock-dossier` (single-name full dossier where shareholder behaviour is one sub-section): this skill goes deep on **just** the ownership-structure dimension across periods.

## Shareholder Structure Model (read before analysis)

Three interfaces, three angles. All are **disclosure-frequency** (typically quarterly, plus mid-quarter 户数 updates for some names) — **not** daily — and lag the period-end.

- **Holder count (`get_holder_count`)** — `holders` / `a_holders` (股东户数 / A股股东户数), `avg_holders` / `avg_a_holders` / `avg_circulation_holders` (户均持股数). Fewer holders with rising 户均持股 usually means chips are **concentrating** (fewer accounts hold more each); the reverse means **dispersing**. `date` is the announcement date, `end_date` the period the count refers to — key on `end_date`.
- **Top holders (`get_top_holders`)** — one row per ranked holder, with `hold_percent_float` (占流通A股比例) and `hold_percent_total` (占总股本比例), `holder_name`, `holder_kind`/`holder_attr`, and `pledge` / `freeze`. Sum the top N (e.g. top 10) `hold_percent_*` for a **concentration ratio**. `stock_type` = `flow` (流通口径) vs `total` (总股本口径) — **never mix the two**. A high top-holder ratio driven by a 控股股东/国资 block is *locked* concentration, not free-floating tradable chips — distinguish it.
- **Share float (`get_share_float`)** — `circulation_a` (流通A股), `free_circulation` (自由流通股本), `non_circulation_a`, `total` / `total_a`. `free_circulation / total` = free-float share; a small free float means the same amount of buying/selling moves the price more. Use it to contextualise concentration (concentration among a tiny free float ≠ concentration of the whole cap).
- **Trend, not level** — the signal is the **change across periods** (户数环比、集中度环比、自由流通占比变化), not any single snapshot. Always pull several periods and read the direction.

## Workflow

1. Resolve the target: a single name or a small watchlist. Confirm how many disclosure periods to look back (default last ~4–6 periods / ~18 months).
2. Read `references/holder-structure-playbook.md` before the first run in a session. Use it for the routing table, the three-interface field model, the concentration/trend definitions, the caliber (flow vs total) rules, the report skeleton, empty-data handling, and the QA checklist.
3. Load `pandadata-api` before any real API call. Open its `references/method-index.md` and the `get_holder_count` / `get_top_holders` / `get_share_float` sections in `references/api-docs.md` to confirm parameters and fields; do not invent parameters, fields, symbols, or credentials.
4. Collect evidence per name:
   - Holder count trend: `get_holder_count` over the lookback window.
   - Top-holder concentration: `get_top_holders` (choose one `stock_type` caliber and state it; e.g. `flow`, `start_rank=1`, `end_rank=10`).
   - Float context: `get_share_float` for the latest period (and a couple back for free-float trend).
   - Identity & industry: `get_stock_detail` and `get_stock_industry` for naming/rollup.
   - Calendar: `get_last_trade_date` / `get_trade_cal` to bound windows where needed.
5. Compute: 户数环比变化 & 户均持股趋势; top-N 合计占比 per period and its change; 自由流通占比 and its change; and a **concentration-direction read** (集中 / 分散 / 稳定) combining 户数↓+户均↑+top-N占比↑ signals. Note pledge/freeze among top holders as a risk flag. Keep raw disclosure dates and calibers with every figure.
6. Generate the Markdown report following the skeleton in the playbook. Save to `reports/holder-structure/<scope>-<date>.md` (e.g. `reports/holder-structure/000001SZ-20260706.md`) unless the user gives another path.
7. Run `scripts/validate_report.py <report-path>` after writing. Fix missing sections, missing source notes, a missing caliber (flow/total) label, a missing disclosure-frequency/lag caveat, missing period labels, or a missing disclaimer before presenting the result.

## Interface Map

Routing aid only; the exact call contract must still come from `pandadata-api`.

| Report section | Lead methods | What it answers |
|---|---|---|
| 股东户数趋势 | `get_holder_count` | Is holder count rising/falling; 户均持股 direction. |
| 前十大集中度 | `get_top_holders` | Top-N 合计占比 (state flow/total caliber) and its change. |
| 自由流通占比 | `get_share_float` | How much of the cap is actually free-floating. |
| 筹码集中方向 | all three combined | 集中 / 分散 / 稳定 read across periods. |
| 大股东质押/冻结 | `get_top_holders` (`pledge`, `freeze`) | Pledge/freeze among top holders as a risk flag. |
| 行业对照（可选） | `get_stock_industry` | Optional peer context for a watchlist. |

## Analysis Modes

- **Single-name structure timeline**: 户数 & 户均持股 over periods, top-10 concentration trend (one caliber), free-float share, and a combined concentration-direction verdict with the disclosure dates behind it.
- **Small watchlist compare**: same metrics side by side for a handful of names; rank by concentration level and by 户数环比降幅. State that names may disclose on different dates — do not compare across mismatched periods without noting it.
- **Concentration read**: 户数↓ + 户均持股↑ + top-N占比↑ over consecutive periods ⇒ "筹码趋于集中"; the reverse ⇒ "趋于分散". A high top-holder ratio that is a locked 控股/国资 block is **structural**, not tradable concentration — say so.
- **Free-float context**: always pair concentration with free-float share — concentration among a very small free float has outsized price sensitivity; a huge free float dilutes any single holder's sway.

## Report Rules

- Write in Chinese unless the user requests another language.
- **Always label the caliber.** Top-holder ratios differ under 流通口径 (`hold_percent_float`) vs 总股本口径 (`hold_percent_total`); pick one, label it, and never mix within a comparison.
- **Always state disclosure frequency and lag.** These are quarterly/periodic figures that lag the period-end; a "trend" needs several periods. Never present one snapshot as a live position.
- Distinguish **locked** concentration (控股股东/国资/limited-sale) from **tradable/free-float** concentration; a high top-holder ratio is not automatically a squeeze setup.
- Separate facts (raw 户数, 占比, 股本), derived metrics (环比变化, top-N 合计, 自由流通占比, direction read), and judgment. Label all derived calculations.
- Treat empty API results as evidence. State "无数据" with the method name and queried window/period instead of silently omitting a section.
- Keep the tone factual and structural. Use "筹码趋于集中/分散", "需结合股价与解禁一并看", "自由流通占比偏低使股价对成交更敏感" rather than directional calls; never give trading instructions or personalized investment advice.

## Automation (optional scheduling)

When the user asks for automated structure monitoring, create a task that runs around disclosure windows (e.g. weekly, or after quarter-end reporting deadlines) rather than daily — these figures update on disclosure, not每日. Make it idempotent: if `reports/holder-structure/<scope>-<date>.md` exists, regenerate and overwrite.

## Resource Guide

- `references/holder-structure-playbook.md`: routing table, three-interface field model, concentration/trend definitions, caliber rules, report skeleton, empty-data handling, and the QA checklist.
- `scripts/validate_report.py`: checks the report for required sections, source notes, the caliber label, the disclosure-frequency/lag caveat, period labels, and the disclaimer.

## Quality Bar

- Every material claim traces to `get_holder_count` / `get_top_holders` / `get_share_float`, a disclosure date, and the period.
- Top-holder concentration always carries its caliber (flow vs total) and is never mixed across calibers.
- A trend read is built from several periods, with the disclosure-frequency/lag caveat stated.
- Locked (控股/国资) concentration is distinguished from free-float concentration.
- End every report with this disclaimer: `本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。`
