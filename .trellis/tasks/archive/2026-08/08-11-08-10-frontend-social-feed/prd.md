# Phase 5: 前端 UI 重构

## Goal

将现有"公众号 Tab + 微博 Tab"的社交页面重构为统一的订阅动态 Feed，支持跨平台订阅管理、AIHot 排行榜和收藏功能。

## Requirements

1. **统一 Feed 页面**：替换原有的 Tab 切换，展示跨平台混合内容
2. **订阅管理**：支持搜索发布者、添加/取消订阅
3. **AIHot 排行榜**：独立页面展示 AIHot 排行
4. **收藏功能**：支持收藏/取消收藏内容
5. **正文详情**：点击内容可查看全文
6. **响应式设计**：移动端和桌面端适配

## Constraints

- 使用 React + TailwindCSS
- 保持现有设计风格
- API 已在 Phase 1-4 完成

## Acceptance Criteria

- [x] Feed 页面展示跨平台内容
- [x] 订阅管理页面可用
- [x] AIHot 排行榜页面可用
- [x] 收藏功能正常
- [x] 正文详情页可用
- [x] 移动端适配正常
