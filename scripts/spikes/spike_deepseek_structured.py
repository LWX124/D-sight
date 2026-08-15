"""DeepSeek 结构化输出与并发 spike。

验证：
1. deepseek-v4-flash 与 deepseek-v4-pro 模型 ID 有效
2. 结构化输出（JSON Schema）可靠性
3. 并发 8 个调用的响应时间和成功率
"""
import asyncio
import json
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / "backend" / ".env")
except ImportError:
    pass

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

# DeepSeek API 不支持 response_format.type=json_schema，只支持 json_object。
# 因此在 prompt 中内嵌 schema 描述，让模型输出 JSON object，再在客户端用
# Pydantic 校验（生产代码由 app.deep_analysis.llm 封装此约束）。
PROMPT = """你是一个基本面分析模块。
数据：PE=18, ROE=28%, 负债率=35%

输出严格的 JSON，格式如下：
{
  "signal": "bullish | bearish | neutral",
  "confidence": 0到100的整数,
  "reasoning": "不超过200字的理由"
}
只输出 JSON，不要其他文字。"""


async def call_model(client, model: str, call_id: int) -> dict:
    start = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            response_format={"type": "json_object"},
            timeout=30,
        )
        elapsed = time.time() - start
        content = resp.choices[0].message.content
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
        times_sorted = sorted(times)
        p50 = times_sorted[len(times_sorted) // 2]
        p95 = times_sorted[-1] if len(times_sorted) < 20 else times_sorted[int(len(times_sorted) * 0.95)]
        print(f"  耗时: min={min(times):.2f}s, max={max(times):.2f}s, avg={sum(times)/len(times):.2f}s, p50={p50:.2f}s, p95={p95:.2f}s")
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

    out = Path("scripts/spikes/spike_deepseek_raw.json")
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"\n原始结果已写入 {out}")


asyncio.run(main())
