# Phase 0 Spike 总结报告

日期：2026-07-29

## 结论

| 项目 | 状态 | 备注 |
|---|---|---|
| ai-hedge-fund 许可证 | **GO** | MIT License，允许商用/修改/再分发，需保留版权声明 |
| A 股数据覆盖率 | **GO** | prices/financial_metrics/income/balance/cashflow 3 标的全通过，company_info 用替代接口 |
| DeepSeek 模型可用性 | **GO** | 两个模型 ID 有效，json_object + Pydantic 方案，并发 8 成功率 100% |

## Phase 1 输入

1. **许可证允许复用的内容**：方法论逻辑、估值公式、数据结构设计、agent 编排模式、信号输出契约结构。UI 必须将投资者姓名替换为方法论名称（设计文档 6.1）。需在源码/文档保留 MIT 版权声明。

2. **A 股数据精确接口**：参见 `spike_a_share_result.md`

3. **模型 ID 锁定**：
   - analyst = `deepseek-v4-flash`（P95 2.42s）
   - portfolio manager = `deepseek-v4-pro`（P95 5.00s）

4. **结构化输出约束**：DeepSeek 不支持 `json_schema`，只能用 `json_object`。prompt 内嵌 schema，客户端 Pydantic 严格校验。

5. **并发上限建议**：analyst 全局 semaphore 默认 8（与设计文档第 6.3 节一致），实测无 429。

## 风险与阻塞项

无 NO-GO 项。两个需 Phase 2 关注的点：

- `stock_individual_info_em` 在 akshare 1.18.64 崩溃，adapter 必须绕行（spot_em + board_industry 组合）。
- 财报表列名随 akshare 版本可能漂移，Phase 2 需契约测试 fixture 锁定。

## Phase 1 开始条件

- [x] 所有 spike 均为 GO
- [x] 许可证核验完成
- [x] A 股字段映射表已锁定
- [x] 模型 ID 已验证
