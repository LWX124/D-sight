# RedFox 社媒采集可行性门禁报告

**日期**: 2026-08-10
**API Key**: ak_e33f...5ff5
**测试结果**: 8/9 通过

## 1. 已确认可用的 API 端点

| 平台 | 端点 | 路径 | 状态 |
|---|---|---|---|
| 公众号 | 搜索账号 | `POST /story/api/gzhData/searchUser` | ✅ |
| 公众号 | 账号作品列表 | `POST /story/api/gzhData/queryWorkList` | ✅ |
| 小红书 | 搜索账号 | `POST /story/api/xhsUser/searchUser` | ✅ |
| 小红书 | 账号详情 | `POST /story/api/xhsUser/queryAccountDetail` | ✅ |
| 小红书 | 搜索作品 | `POST /story/api/xhsUser/searchArticle` | ✅ |
| 小红书 | 作品详情 | `POST /story/api/xhsUser/queryWorkDetail` | ✅ |
| 小红书 | 账号作品列表 | — | ❌ **不存在** |
| B站 | 搜索账号 | `POST /story/api/bili/data/accountSearch` | ✅ |
| B站 | 账号作品列表 | `POST /story/api/bili/data/accountWorkList` | ✅ |

## 2. 字段覆盖率

### 公众号作品字段

| 字段 | 覆盖 | 说明 |
|---|---|---|
| 唯一ID | ✅ | `workUuid` |
| 标题 | ✅ | `title` |
| 作者 | ✅ | `author` / `accountName` |
| 发布时间 | ✅ | `publishTime` |
| 封面 | ✅ | `coverUrl` |
| 阅读数 | ✅ | `readCount` |
| 点赞数 | ✅ | `likeCount` |
| 收藏数 | ✅ | `collectCount` |
| 分享数 | ✅ | `shareCount` |
| 评论数 | ✅ | `commentCount` |
| 原文链接 | ✅ | `workUrl` / `sourceUrl` |
| 摘要 | ✅ | `summary` / `memo` |

### 小红书作品字段

| 字段 | 覆盖 | 说明 |
|---|---|---|
| 唯一ID | ✅ | `workId` |
| 标题 | ✅ | `workTitle` |
| 作者 | ✅ | `accountNickname` / `accountUserid` |
| 发布时间 | ✅ | `workPublishTime` |
| 封面 | ✅ | `coverUrl` |
| 点赞数 | ✅ | `workLikedCount` |
| 收藏数 | ✅ | `workCollectedCount` |
| 评论数 | ✅ | `workCommentsCount` |
| 转发数 | ✅ | `workSharedCount` |
| 内容描述 | ✅ | `workDesc` |
| 作品类型 | ✅ | `workType` (视频/图文) |
| 作品链接 | ✅ | `workUrl` |

### B站作品字段

| 字段 | 覆盖 | 说明 |
|---|---|---|
| 唯一ID | ✅ | `bvId` |
| 标题 | ✅ | `title` |
| 作者 | ✅ | `author` |
| 发布时间 | ✅ | `created` |
| 封面 | ✅ | `picUrl` |
| 播放数 | ✅ | `playCount` |
| 点赞数 | ✅ | `likeCount` |
| 投币数 | ✅ | `coinCount` |
| 收藏数 | ✅ | `favoriteCount` |
| 弹幕数 | ✅ | `videoReview` |
| 评论数 | ✅ | `commentCount` |
| 分享数 | ✅ | `shareCount` |
| 时长 | ✅ | `duration` |
| 分类 | ✅ | `firstType` / `secondType` |
| 标签 | ✅ | `tagNames` |
| 描述 | ✅ | `description` |

## 3. 关键发现

### 3.1 小红书无账号作品列表接口

**影响**：
- 无法订阅特定小红书账号并获取其全部作品
- 订阅动态场景下，小红书只能通过搜索关键词发现内容
- AIHot 可通过搜索接口采集金融内容，但无法做逐账号定时同步

**建议**：
- 小红书订阅功能降级为搜索发现，不作为核心订阅平台
- AIHot 通过搜索关键词（如"金融""股票""基金"）采集小红书内容

### 3.2 无金融聚合榜接口

**影响**：
- RedFox 不提供按金融主题聚合的热榜接口
- AIHot 需要自行通过搜索关键词 + 排名算法实现

**建议**：
- AIHot 通过搜索关键词采集各平台金融内容
- 使用自有排名公式（AIHotScore）计算热度

### 3.3 无视频号接口

**影响**：
- 视频号接口标记为"即将上线"
- 首期不接入视频号

## 4. 费用估算

- 每次 API 调用：¥0.02 起（阶梯定价）
- 每日采集成本估算：
  - 公众号：3 个号 × 8 次/天 × ¥0.02 = ¥0.48/天
  - B站：3 个号 × 8 次/天 × ¥0.02 = ¥0.48/天
  - 小红书搜索：3 次/天 × ¥0.02 = ¥0.06/天
  - 合计：约 ¥1.02/天，¥30.6/月

## 5. 门禁结论

**通过条件**：
- ✅ 公众号搜索账号和作品列表可用
- ✅ 小红书搜索账号、作品和详情可用
- ✅ B站搜索账号和作品列表可用
- ✅ 所有必需字段（ID、时间、作者、标题、互动指标）已覆盖
- ⚠️ 小红书无账号作品列表接口（已确认，设计已调整）

**不通过条件**：
- ❌ 金融聚合榜接口不存在（需通过搜索关键词实现）
- ❌ 视频号接口不可用（首期不接入）

**结论**：**门禁通过**，可以进入 Phase 1 实现。小红书订阅功能需降级为搜索发现。
