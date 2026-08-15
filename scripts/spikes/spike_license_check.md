# ai-hedge-fund 许可证核验结果

日期：2026-07-29

## 许可证类型

**MIT License**（Copyright (c) 2024 Virat Singh）

仓库路径：`/Users/weixi1/Documents/Study/ai-hedge-fund`

## 权限范围

| 权限 | 是否允许 |
|---|---|
| 商用 | ✅ 允许 |
| 修改 | ✅ 允许 |
| 再分发 | ✅ 允许 |
| 私用 | ✅ 允许 |
| 闭源衍生 | ✅ 允许 |
| 署名要求 | ⚠️ MIT 仅要求保留版权声明与许可证文本，无强制署名条款 |
| 免责声明 | 明确声明"仅用于教育与研究，非真实交易或投资" |

## prompt 与方法论可复用边界

ai-hedge-fund 的 README 明确声明项目"仅用于教育目的"。其 prompt 以真实投资者姓名命名（Warren Buffett、Ben Graham 等），但这些姓名本身是公开人物，prompt 内容属于方法论描述而非受版权保护的创意作品。MIT 许可证覆盖源码与文档，包括 prompt 文本。

**可直接复用的部分：**
- 数据结构设计（MarketData、FinancialMetrics 字段定义）
- 方法论逻辑（估值公式、技术指标计算、风险指标计算）
- agent 编排模式（fan-out + 汇总 + 风险约束）
- 信号输出契约结构（signal/confidence/reasoning）

**需要重写的部分：**
- 按 D-sight 设计文档第 6.1 节，方法论改用"护城河价值""安全边际"等中性名称展示，内部稳定 ID 保留来源映射，但 UI 注明"受某投资方法启发，不代表本人观点"
- 适配 A 股/港股/美股三市场统一证据契约，不复用其针对美股的硬编码数据源
- 移除与真实交易、订单执行相关的代码（设计文档非目标）

## 许可证合规要求

在 D-sight 深度分析模块的源码或文档中保留以下版权声明：

```
This software includes methodology inspired by ai-hedge-fund
(https://github.com/virattt/ai-hedge-fund), licensed under the MIT License.
Copyright (c) 2024 Virat Singh.
```

## Go/No-Go

ai-hedge-fund 许可证核验：**GO**

MIT 许可证允许商用、修改与再分发，可自由复用方法论、数据结构与 prompt 逻辑。需保留版权声明，并将 UI 中的投资者姓名替换为方法论名称以满足设计文档合规要求。
