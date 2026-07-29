# 深度分析 Phase 0：数据与许可证 Spike 计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在第一行生产代码落地前，验证数据可用性和 spike 结论，产出 go/no-go 报告。

**Architecture:** 纯探索脚本，不写进任何应用目录。结果写入 `docs/superpowers/spikes/` 作为 Phase 1 的输入。

**Tech Stack:** Python 3.12、akshare、yfinance（需先添加依赖）、DeepSeek API

## Global Constraints

- 不修改 `backend/app/` 下任何文件
- 不写 Alembic migration
- 脚本放在 `scripts/spikes/` 目录，不在测试路径
- 所有 spike 结果写为 Markdown 文档，供 Phase 1 参考
- ai-hedge-fund 位于 `/Users/weixi1/Documents/Study/ai-hedge-fund`

---

### Task 0.1：核验 ai-hedge-fund 许可证与可复用边界

**Files:**
- Create: `scripts/spikes/spike_license_check.md`

**Interfaces:**
- Produces: 许可证类型、可复用的内容范围（prompt 结构/方法论/代码）

- [ ] **Step 1: 检查仓库许可证文件**

```bash
cat /Users/weixi1/Documents/Study/ai-hedge-fund/LICENSE 2>/dev/null || \
cat /Users/weixi1/Documents/Study/ai-hedge-fund/LICENSE.md 2>/dev/null || \
echo "未找到 LICENSE 文件，检查 README"
head -50 /Users/weixi1/Documents/Study/ai-hedge-fund/README.md
```

- [ ] **Step 2: 记录许可证结论**

创建 `scripts/spikes/spike_license_check.md`，记录：
- 许可证类型（MIT/Apache/GPL/其他）
- 是否允许商用、修改、再分发
- prompt 内容是否受版权保护
- 可直接复用的部分（数据结构、方法论逻辑）
- 必须重写的部分（如 prompt 涉及具体人名且受限）

- [ ] **Step 3: Commit**

```bash
cd /Users/weixi1/Documents/mine/D-sight
git add scripts/spikes/spike_license_check.md
git commit -m "docs(spike): 记录 ai-hedge-fund 许可证核验结果"
```

---

### Task 0.2：A 股数据接口 spike

**Files:**
- Create: `scripts/spikes/spike_a_share_data.py`
- Create: `scripts/spikes/spike_a_share_result.md`

**Interfaces:**
- Produces: 三个 A 股标的的完整 MarketData 字段覆盖率表格

- [ ] **Step 1: 确认 akshare 已安装**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 -c "import akshare; print(akshare.__version__)"
```

Expected: 打印版本号（1.18.64+）

- [ ] **Step 2: 编写 A 股数据 spike 脚本**

创建 `scripts/spikes/spike_a_share_data.py`：

```python
"""A 股数据接口 spike：验证字段覆盖率。

测试标的：
- 600519.SH 贵州茅台（大盘消费）
- 000001.SZ 平安银行（金融）
- 300750.SZ 宁德时代（科创）

验证的 MarketData 字段：
- prices: 近90日日线（date/open/high/low/close/volume）
- financial_metrics: PE/PB/ROE/负债率
- income: 营收/净利润/毛利率（近4~8期）
- balance: 总资产/总负债/净资产/现金（近4期）
- cashflow: 经营/投资/筹资现金流（近4期）
- company_name, exchange, industry
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    import akshare as ak
except ImportError:
    print("ERROR: akshare 未安装，运行: pip install akshare")
    sys.exit(1)

TICKERS = [
    ("600519", "SH", "贵州茅台"),
    ("000001", "SZ", "平安银行"),
    ("300750", "SZ", "宁德时代"),
]

results = {}

for code, exchange, name in TICKERS:
    print(f"\n===== {name} ({code}.{exchange}) =====")
    r = {"ticker": f"{code}.{exchange}", "name": name, "fields": }

    # 1. 日线价格
    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(date.today() - timedelta(days=90)).strftime("%Y%m%d"),
            end_date=date.today().strftime("%Y%m%d"),
            adjust="qfq",
        )
        r["fields"]["prices"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns),
            "sample": df.tail(2).to_dict("records"),
        }
        print(f"  prices: {len(df)} 行, 列={list(df.columns)}")
    except Exception as e:
        r["fields"]["prices"] = {"ok": False, "error": str(e)}
        print(f"  prices: ERROR {e}")

    # 2. 财务比率
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year="2022")
        r["fields"]["financial_metrics"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:20],  # 前20列
        }
        print(f"  financial_metrics: {len(df)} 行, {len(df.columns)} 列")
    except Exception as e:
        r["fields"]["financial_metrics"] = {"ok": False, "error": str(e)}
        print(f"  financial_metrics: ERROR {e}")

    # 3. 利润表
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="利润表")
        r["fields"]["income"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:10],
        }
        print(f"  income: {len(df)} 行")
    except Exception as e:
        r["fields"]["income"] = {"ok": False, "error": str(e)}
        print(f"  income: ERROR {e}")

    # 4. 资产负债表
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="资产负债表")
        r["fields"]["balance"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:10],
        }
        print(f"  balance: {len(df)} 行")
    except Exception as e:
        r["fields"]["balance"] = {"ok": False, "error": str(e)}
        print(f"  balance: ERROR {e}")

    # 5. 现金流量表
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="现金流量表")
        r["fields"]["cashflow"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:10],
        }
        print(f"  cashflow: {len(df)} 行")
    except Exception as e:
        r["fields"]["cashflow"] = {"ok": False, "error": str(e)}
        print(f"  cashflow: ERROR {e}")

    # 6. 公司信息
    try:
        df = ak.stock_individual_info_em(symbol=code)
        r["fields"]["company_info"] = {
            "ok": True,
            "data": dict(zip(df.iloc[:, 0], df.iloc[:, 1])),
        }
        print(f"  company_info: OK")
    except Exception as e:
        r["fields"]["company_info"] = {"ok": False, "error": str(e)}
        print(f"  company_info: ERROR {e}")

    results[code] = r

out = Path("scripts/spikes/spike_a_share_raw.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
print(f"\n原始结果已写入 {out}")

# 覆盖率统计
print("\n===== 字段覆盖率摘要 =====")
fields = ["prices", "financial_metrics", "income", "balance", "cashflow", "company_info"]
for f in fields:
    ok_count = sum(1 for r in results.values() if r["fields"].get(f, {}).get("ok"))
    print(f"  {f}: {ok_count}/{len(TICKERS)} 成功")
```

- [ ] **Step 3: 运行脚本**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 ../scripts/spikes/spike_a_share_data.py 2>&1 | tee ../scripts/spikes/spike_a_share_output.txt
```

Expected: 至少 `prices`、`financial_metrics`、`income`、`balance` 全部成功

- [ ] **Step 4: 记录字段映射**

创建 `scripts/spikes/spike_a_share_result.md`，内容模板：

```markdown
# A 股数据接口 Spike 结果

日期：{今天}

## 覆盖率

| 字段 | 600519 茅台 | 000001 平安银行 | 300750 宁德时代 | 备注 |
|---|---|---|---|---|
| prices | ✓ | ✓ | ✓ | akshare.stock_zh_a_hist |
| financial_metrics | ✓ | ✓ | ✓ | akshare.stock_financial_analysis_indicator |
| income | ✓ | ✓ | ✓ | akshare.stock_financial_report_sina(利润表) |
| balance | ✓ | ✓ | ✓ | akshare.stock_financial_report_sina(资产负债表) |
| cashflow | ✓ | ✓ | ✓ | akshare.stock_financial_report_sina(现金流量表) |
| company_info | ✓ | ✓ | ✓ | akshare.stock_individual_info_em |

## 关键字段确认

### MarketData 必需字段映射
| MarketData 字段 | A 股数据源 | 列名 | 单位 | 备注 |
|---|---|---|---|---|
| close | stock_zh_a_hist | 收盘 | 元 | 前复权 |
| pe_ratio | stock_financial_analysis_indicator | 市盈率 | 倍 | |
| roe_ttm | stock_financial_analysis_indicator | 净资产收益率 | % | |
| revenue | stock_financial_report_sina 利润表 | 营业总收入 | 元 | |
| net_income | stock_financial_report_sina 利润表 | 净利润 | 元 | |
| total_assets | stock_financial_report_sina 资产负债表 | 资产总计 | 元 | |
| cash | stock_financial_report_sina 资产负债表 | 货币资金 | 元 | |
| operating_cf | stock_financial_report_sina 现金流量表 | 经营活动产生的现金流量净额 | 元 | |

## 缺失/不可用字段

（如有，记录在此）

## Go/No-Go

A 股数据：**GO** / NO-GO（删除不适用项）
```

- [ ] **Step 5: Commit**

```bash
cd /Users/weixi1/Documents/mine/D-sight
git add scripts/spikes/
git commit -m "docs(spike): A 股数据接口 spike 结果"
```

---

### Task 0.3：DeepSeek 结构化输出与并发 spike

**Files:**
- Create: `scripts/spikes/spike_deepseek_structured.py`
- Create: `scripts/spikes/spike_deepseek_result.md`

**Interfaces:**
- Consumes: `.env` 中的 `DEEPSEEK_API_KEY`
- Produces: 模型 ID 确认、结构化输出成功率、并发响应时间

- [ ] **Step 1: 编写 DeepSeek spike 脚本**

创建 `scripts/spikes/spike_deepseek_structured.py`：

```python
"""DeepSeek 结构化输出与并发 spike。

验证：
1. deepseek-v4-flash 与 deepseek-v4-pro 模型 ID 有效
2. 结构化输出（JSON Schema）可靠性
3. 并发 8 个调用的响应时间和成功率
"""
import asyncio
import os
import time
from pathlib import Path

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / "backend" / ".env")
except ImportError:
    pass  # 手动设置环境变量

from openai import AsyncOpenAI

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = "https://api.deepseek.com"

ANALYST_SCHEMA = {
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "reasoning": {"type": "string", "maxLength": 200},
    },
    "required": ["signal", "confidence", "reasoning"],
    "additionalProperties": False,
}

PROMPT = """你是一个基本面分析模块。
数据：PE=18, ROE=28%, 负债率=35%
输出分析信号（JSON格式）。"""

async def call_model(client, model: str, call_id: int) -> dict:
    start = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "analyst_signal",
                    "schema": ANALYST_SCHEMA,
                    "strict": True,
                },
            },
            timeout=30,
        )
        elapsed = time.time() - start
        content = resp.choices[0].message.content
        import json
        parsed = json.loads(content)
        # 校验
        assert parsed["signal"] in ("bullish", "bearish", "neutral")
        assert 0 <= parsed["confidence"] <= 100
        assert isinstance(parsed["reasoning"], str)
        return {"id": call_id, "ok": True, "elapsed_s": round(elapsed, 2),
                "signal": parsed["signal"], "confidence": parsed["confidence"],
                "model": model, "tokens": resp.usage.total_tokens}
    except Exception as e:
        return {"id": call_id, "ok": False, "elapsed_s": round(time.time() - start, 2),
                "error": str(e), "model": model}

async def test_model(model: str, concurrency: int = 8):
    print(f"\n--- 测试 {model} (并发={concurrency}) ---")
    async with AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL) as client:
        tasks = [call_model(client, model, i) for i in range(concurrency)]
        results = await asyncio.gather(*tasks)

    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    times = [r["elapsed_s"] for r in ok]

    print(f"  成功: {len(ok)}/{concurrency}")
    if times:
        print(f"  耗时: min={min(times):.2f}s, max={max(times):.2f}s, avg={sum(times)/len(times):.2f}s")
    if fail:
        for f in fail:
            print(f"  FAIL #{f['id']}: {f['error']}")
    return results

async def main():
    if not API_KEY:
        print("ERROR: DEEPSEEK_API_KEY 未设置")
        return

    all_results = {}
    for model in ["deepseek-v4-flash", "deepseek-v4-pro"]:
        results = await test_model(model, concurrency=8)
        all_results[model] = results

    import json
    out = Path("scripts/spikes/spike_deepseek_raw.json")
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"\n原始结果已写入 {out}")

asyncio.run(main())
```

- [ ] **Step 2: 运行脚本（在 backend venv 内）**

```bash
cd /Users/weixi1/Documents/mine/D-sight/backend
python3 ../scripts/spikes/spike_deepseek_structured.py 2>&1 | tee ../scripts/spikes/spike_deepseek_output.txt
```

Expected: 两个模型各 8 并发，成功率 ≥ 7/8，P95 < 10s

- [ ] **Step 3: 记录结论**

创建 `scripts/spikes/spike_deepseek_result.md`：

```markdown
# DeepSeek 结构化输出 Spike 结果

日期：{今天}

## 模型 ID 确认
- deepseek-v4-flash：有效 / 无效
- deepseek-v4-pro：有效 / 无效

## 结构化输出成功率
| 模型 | 并发数 | 成功率 | P50 耗时 | P95 耗时 |
|---|---|---|---|---|
| deepseek-v4-flash | 8 | ?/8 | ?s | ?s |
| deepseek-v4-pro | 8 | ?/8 | ?s | ?s |

## 速率限制
（记录是否遇到 429，触发的 RPM/TPM 阈值）

## Go/No-Go
DeepSeek 结构化输出：**GO** / NO-GO
```

- [ ] **Step 4: Commit**

```bash
cd /Users/weixi1/Documents/mine/D-sight
git add scripts/spikes/
git commit -m "docs(spike): DeepSeek 结构化输出与并发 spike 结果"
```

---

### Task 0.4：Phase 0 总结报告

**Files:**
- Create: `scripts/spikes/PHASE0_SUMMARY.md`

**Interfaces:**
- Consumes: Task 0.1–0.3 所有 spike 结果

- [ ] **Step 1: 创建 Phase 0 总结**

创建 `scripts/spikes/PHASE0_SUMMARY.md`：

```markdown
# Phase 0 Spike 总结报告

日期：{今天}

## 结论

| 项目 | 状态 | 备注 |
|---|---|---|
| ai-hedge-fund 许可证 | GO/NO-GO | |
| A 股数据覆盖率 | GO/NO-GO | |
| DeepSeek 模型可用性 | GO/NO-GO | |

## Phase 1 输入

1. 许可证允许复用的内容：...
2. A 股数据精确接口：参见 spike_a_share_result.md
3. 模型 ID 锁定：analyst=deepseek-v4-flash, portfolio=deepseek-v4-pro
4. 并发上限建议：...

## 风险与阻塞项

（如有任何 NO-GO，在此说明阻塞项和备选方案）

## Phase 1 开始条件

- [ ] 所有 spike 均为 GO
- [ ] 许可证核验完成
- [ ] A 股字段映射表已锁定
- [ ] 模型 ID 已验证
```

- [ ] **Step 2: Commit**

```bash
cd /Users/weixi1/Documents/mine/D-sight
git add scripts/spikes/PHASE0_SUMMARY.md
git commit -m "docs(spike): Phase 0 总结报告"
```
