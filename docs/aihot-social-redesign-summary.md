# AIHot 与社媒数据源重构 — 任务小结

> 日期：2026-08-11  
> 分支：main  
> 状态：代码完成，待数据库验证

---

## 一、项目背景

将现有公众号、微博采集与新增的小红书、B站接入重构为一套统一的社媒内容供给系统，并建立订阅动态和 AIHot 两个产品。

设计文档：`docs/aihot-social-data-redesign.md`

---

## 二、实施概览

共 6 个 Phase，全部代码完成：

| Phase | 内容 | 产出文件数 | 状态 |
|---|---|---|---|
| 0 | RedFox 可行性门禁 | 1 | ✅ 完成 |
| 1 | 统一社媒内核 | 10 | ✅ 完成 |
| 2 | 订阅动态 | 2 | ✅ 完成 |
| 3 | AIHot 数据链路 | 5 | ✅ 完成 |
| 4 | 正文获取与收藏 | 4 | ✅ 完成 |
| 5 | 前端 UI 重构 | 3 | ✅ 完成 |

---

## 三、Phase 0: RedFox 可行性门禁

**目标**：验证 RedFox API 可行性，确认各平台接口路径。

**产出**：
- `docs/redfox-gate-report.md` — 门禁报告

**结论**：
- 公众号：搜索 + 作品列表 ✅
- 小红书：搜索 ✅，作品列表 ❌（无接口）
- B站：搜索 + 作品列表 ✅

---

## 四、Phase 1: 统一社媒内核

**目标**：建立统一数据模型和 Provider Adapter 接口。

**新增表**：
| 表名 | 说明 |
|---|---|
| `social_publishers` | 平台发布者主表 |
| `social_items` | 平台内容主表 |
| `social_item_metric_snapshots` | 互动指标快照 |
| `social_subscriptions` | 用户订阅关系 |
| `social_item_media` | 内容媒体附件 |

**新增文件**：
| 文件 | 说明 |
|---|---|
| `backend/alembic/versions/b2c3d4e5f6a7_unified_social.py` | Alembic migration |
| `backend/app/social/unified_models.py` | ORM models（5 张表） |
| `backend/app/social/providers/__init__.py` | Provider 包 |
| `backend/app/social/providers/base.py` | SocialProvider ABC + DTO dataclasses |
| `backend/app/social/providers/redfox.py` | RedFox Provider（公众号/小红书/B站） |
| `backend/app/social/providers/weibo.py` | 微博 Provider 适配 |
| `backend/app/social/providers/wechat_mp.py` | 公众号备用 Provider 适配 |
| `backend/app/social/unified.py` | 统一 CRUD 层（upsert/get_feed） |
| `scripts/migrate_social_data.py` | 数据回填脚本 |
| `scripts/verify_social_migration.py` | 对账脚本 |

---

## 五、Phase 2: 订阅动态

**目标**：跨平台订阅动态，统一 Feed API。

**新增 API**：
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/social/feed` | 跨平台 Feed（时间倒序） |
| POST | `/api/social/feed/refresh` | 手动刷新（15 分钟冷却） |
| GET | `/api/social/subscriptions` | 列出所有订阅 |
| POST | `/api/social/subscriptions` | 添加订阅 |
| DELETE | `/api/social/subscriptions/{sub_id}` | 取消订阅 |
| GET | `/api/social/publishers/search` | 搜索发布者 |

**新增文件**：
| 文件 | 说明 |
|---|---|
| `backend/app/social/feed_router.py` | 统一订阅动态路由（6 个端点） |

**修改文件**：
| 文件 | 变更 |
|---|---|
| `backend/app/social/schemas.py` | 新增 Phase 2 Schemas |
| `backend/app/social/router.py` | 注册 feed_router |
| `backend/app/core/config.py` | 新增 `redfox_api_key` 配置 |
| `backend/.env` | 新增 REDFOX_API_KEY |

---

## 六、Phase 3: AIHot 数据链路

**目标**：金融信源池管理、批次采集、指标快照、排名计算、失败降级。

**新增表**：
| 表名 | 说明 |
|---|---|
| `hot_source_memberships` | 金融信源池成员 |
| `hot_runs` | 批次采集记录 |
| `hot_rankings` | AIHot 排名 |
| `provider_call_logs` | Provider 调用日志 |

**新增 API**：
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/aihot` | AIHot 排行榜（window/category/q/limit） |
| POST | `/api/aihot/refresh` | 手动触发采集 |
| GET | `/api/aihot/sources` | 列出信源池 |
| POST | `/api/aihot/sources` | 添加信源 |
| DELETE | `/api/aihot/sources/{id}` | 移除信源 |

**新增文件**：
| 文件 | 说明 |
|---|---|
| `backend/alembic/versions/c3d4e5f6a7b8_aihot_pipeline.py` | AIHot 表 migration |
| `backend/app/aihot/__init__.py` | 模块初始化 |
| `backend/app/aihot/models.py` | ORM models（4 张表） |
| `backend/app/aihot/ranking.py` | AIHotScore 计算（权重+时效+来源乘数） |
| `backend/app/aihot/pipeline.py` | 批次采集流程 |
| `backend/app/aihot/router.py` | AIHot API（5 个端点） |

**AIHotScore 公式**：
```
AIHotScore = Σ(metric_i × weight_i) × recency_factor × source_multiplier
```

权重默认值：like=1.0, comment=3.0, share=5.0, collect=2.0, view=0.01, read=0.005

时效因子：< 2h: 1.5, < 6h: 1.2, < 24h: 1.0, < 72h: 0.6, >= 72h: 0.3

---

## 七、Phase 4: 正文获取与收藏

**目标**：正文缓存策略和收藏功能。

**新增表**：
| 表名 | 说明 |
|---|---|
| `content_bookmarks` | 内容收藏 |

**新增 API**：
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/social/bookmarks` | 收藏内容 |
| DELETE | `/api/social/bookmarks/{item_id}` | 取消收藏 |
| GET | `/api/social/bookmarks` | 列出收藏 |

**新增文件**：
| 文件 | 说明 |
|---|---|
| `backend/alembic/versions/d4e5f6a7b8c9_content_bookmarks.py` | 收藏表 migration |
| `backend/app/social/body_fetch.py` | 正文获取与缓存（90天/7天 TTL） |
| `backend/app/social/bookmarks.py` | 收藏 CRUD |
| `backend/app/social/bookmark_router.py` | 收藏路由（3 个端点） |

---

## 八、Phase 5: 前端 UI 重构

**目标**：统一订阅动态 Feed，AIHot 排行榜页面。

**新增文件**：
| 文件 | 说明 |
|---|---|
| `frontend/src/panels/social/UnifiedFeed.tsx` | 统一订阅动态 Feed 组件 |
| `frontend/src/panels/social/AihotPanel.tsx` | AIHot 排行榜组件 |

**修改文件**：
| 文件 | 变更 |
|---|---|
| `frontend/src/panels/SocialPanel.tsx` | 替换为统一 Tab（订阅动态 + AIHot） |
| `frontend/src/lib/social.ts` | 新增统一 API 函数（Feed/订阅/收藏） |

---

## 九、数据库 Migration 汇总

| Migration | 说明 |
|---|---|
| `b2c3d4e5f6a7_unified_social.py` | 统一社媒表（5 张） |
| `c3d4e5f6a7b8_aihot_pipeline.py` | AIHot 表（4 张） |
| `d4e5f6a7b8c9_content_bookmarks.py` | 收藏表（1 张） |

---

## 十、待办事项

### 必须执行（数据库运行后）

```bash
cd backend
alembic upgrade head
python -m scripts.migrate_social_data
python -m scripts.verify_social_migration
```

### 可选配置

| 项目 | 说明 |
|---|---|
| APScheduler | AIHot 批次采集每 2 小时执行 |
| Redis | Feed 刷新冷却（15 分钟） |
| REDFOX_API_KEY | RedFox API 认证 |

### 后续优化

| 项目 | 说明 |
|---|---|
| 微博接入 AIHot | 当前微博不接入 AIHot |
| 小红书作品列表 | RedFox 无接口，待后续支持 |
| 正文详情页 | 前端正文详情页优化 |
| 管理后台 | 信源池管理界面 |

---

## 十一、技术决策

1. **统一表 vs 平台独立表**：选择统一表，便于跨平台 Feed 和 AIHot 排名
2. **Provider Adapter 模式**：抽象统一接口，各平台独立实现
3. **DTO 桥梁**：Provider 返回 DTO，统一 CRUD 层写入 DB
4. **幂等迁移**：依赖 `(platform, external_id)` 唯一约束
5. **正文缓存**：公众号 90 天，其他平台 7 天
6. **AIHotScore**：权重+时效+来源乘数，可配置
7. **失败降级**：Provider 失败不阻断其他平台

---

## 十二、文件清单

### 新增文件（24 个）

**后端**：
- `backend/alembic/versions/b2c3d4e5f6a7_unified_social.py`
- `backend/alembic/versions/c3d4e5f6a7b8_aihot_pipeline.py`
- `backend/alembic/versions/d4e5f6a7b8c9_content_bookmarks.py`
- `backend/app/social/unified_models.py`
- `backend/app/social/providers/__init__.py`
- `backend/app/social/providers/base.py`
- `backend/app/social/providers/redfox.py`
- `backend/app/social/providers/weibo.py`
- `backend/app/social/providers/wechat_mp.py`
- `backend/app/social/unified.py`
- `backend/app/social/feed_router.py`
- `backend/app/social/body_fetch.py`
- `backend/app/social/bookmarks.py`
- `backend/app/social/bookmark_router.py`
- `backend/app/aihot/__init__.py`
- `backend/app/aihot/models.py`
- `backend/app/aihot/ranking.py`
- `backend/app/aihot/pipeline.py`
- `backend/app/aihot/router.py`
- `scripts/migrate_social_data.py`
- `scripts/verify_social_migration.py`

**前端**：
- `frontend/src/panels/social/UnifiedFeed.tsx`
- `frontend/src/panels/social/AihotPanel.tsx`

**文档**：
- `docs/redfox-gate-report.md`

### 修改文件（6 个）

- `backend/app/social/schemas.py`
- `backend/app/social/router.py`
- `backend/app/core/config.py`
- `backend/.env`
- `frontend/src/panels/SocialPanel.tsx`
- `frontend/src/lib/social.ts`
- `docs/aihot-social-data-redesign.md`（§5.2, §6.2 更新）
