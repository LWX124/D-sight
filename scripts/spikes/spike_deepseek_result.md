# DeepSeek 结构化输出 Spike 结果

日期：2026-07-29
DeepSeek API base_url：https://api.deepseek.com

## 模型 ID 确认

| 模型 | 状态 |
|---|---|
| deepseek-v4-flash | ✅ 有效 |
| deepseek-v4-pro | ✅ 有效 |

## 结构化输出方式

**关键发现：DeepSeek API 不支持 `response_format.type="json_schema"`**，返回 `400 This response_format type is unavailable now`。

支持的格式：`response_format.type="json_object"`。

**解决方案：**
- prompt 内嵌 JSON schema 描述，要求模型只输出 JSON object
- 客户端用 Pydantic Schema 做严格校验（枚举、数值范围、字段存在性、长度限制）
- 设计文档第 6.2 节本就要求 LLM 原始输出必须依次通过 JSON 解析 → Pydantic 校验 → 枚举范围校验 → 证据引用校验 → 长度过滤 → 失败一次格式修复重试。json_object + Pydantic 双重校验满足此约束。

## 结构化输出成功率

| 模型 | 并发数 | 成功率 | min | avg | p50 | p95 | max |
|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | 8 | 8/8 | 1.72s | 1.98s | 2.03s | 2.42s | 2.42s |
| deepseek-v4-pro | 8 | 8/8 | 2.76s | 3.60s | 3.43s | 5.00s | 5.00s |

两个模型并发 8 调用，成功率 100%，P95 均低于设计文档要求（analyst 超时 45 秒，任务超时 300 秒）。

## 速率限制

本次并发 8 调用未触发 429。

## 成本分层确认

- analyst 角色：`deepseek-v4-flash`，P95 2.42s，token 量小，成本低
- portfolio manager 角色：`deepseek-v4-pro`，P95 5.00s，判断质量更高
- 与设计文档第 8 节配置一致

## Go/No-Go

DeepSeek 结构化输出：**GO**

模型 ID 有效，json_object + Pydantic 校验方案可靠，并发 8 成功率 100%，延迟在预算内。Phase 2 的 `app.deep_analysis.llm` 模块需封装此约束，统一使用 `response_format={"type": "json_object"}` 并禁止 `json_schema`。
