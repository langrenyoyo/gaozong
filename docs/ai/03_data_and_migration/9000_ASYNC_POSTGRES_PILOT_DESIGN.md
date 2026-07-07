# 9000 Async PostgreSQL 试点设计

任务：P2-F-DB-9000-ASYNC-PG-PILOT-DESIGN-1

范围：本文只做 9000 主服务 async PostgreSQL 接入方案设计和第一个试点模块选择。不连接 PostgreSQL，不切换运行数据库，不修改业务 SQL，不修改表结构，不引入 Alembic，不跑迁移。

## 1. 当前 9000 数据库入口现状

9000 当前中心入口是 `app/database.py`：

1. `DATABASE_URL` 已进入配置抽象。
2. `get_database_runtime()` 可识别 `sqlite` / `postgresql` 并提供脱敏 URL。
3. `create_database_engine()` 当前仅允许 SQLite 创建 SQLAlchemy engine。
4. `SessionLocal` 和 `get_db()` 仍是 FastAPI 主要数据库依赖。
5. PostgreSQL backend 当前只识别、不连接。

当前大多数 9000 router / service 仍使用同步 SQLAlchemy `Session`：

```text
+ API router
+ Depends(get_db)
+ 同步 SQLAlchemy Session
+ service / query
+ SQLite
```

后续 async PostgreSQL 接入不能在每个请求中创建 engine / pool，必须在 FastAPI startup 初始化 pool，在 shutdown 关闭 pool。

## 2. 9000 当前 DB 使用审计结果

### 2.1 高频读接口

| 模块 | 代表路径 | 主要表 | 说明 |
|---|---|---|---|
| 线索列表 | `GET /leads` | `douyin_leads` | 商户侧高频列表，分页、状态、关键词、商户隔离要求高。 |
| AI 回复记录 | `GET /ai-reply-decision-logs` | `ai_reply_decision_logs` | 商户侧审计列表，可能随自动回复增长而高频。 |
| 原始事件 | `GET /webhook-events` | `douyin_webhook_events` | 事件排查列表，可能数据量较大。 |
| 通知记录 | `GET /lead-notifications/records` | `lead_notifications`、`douyin_leads`、`sales_staff` | 需要关联查询和商户隔离。 |
| 微信任务历史 | `GET /wechat-tasks` | `wechat_tasks` | Local Agent 任务历史查询，后续数据增长明显。 |

这些接口适合作为后续性能优化目标，但不适合作为第一个 async PG 试点，因为它们涉及分页、筛选、关联、历史兼容和用户可见主链路。

### 2.2 高频写接口

| 模块 | 代表路径 | 主要表 | 风险 |
|---|---|---|---|
| Webhook 入库 | `POST /webhook/douyin`、`POST /integrations/douyin/webhook` | `douyin_webhook_events`、`douyin_leads` | 幂等、验签、原始事件保留、线索生成，风险高。 |
| 线索同步 | `POST /integrations/douyin/sync-leads` | `douyin_leads` | 上游同步和自动派单相邻，风险高。 |
| 销售分配 | `POST /leads/{lead_id}/assign` | `douyin_leads`、分配相关记录 | 影响业务状态流转。 |
| 微信任务结果回写 | `POST /wechat-tasks/{task_id}/result` | `wechat_tasks`、`reply_checks`、`lead_notifications` | 关联 Local Agent 和回复检测。 |
| AI 回复决策日志 | reply-suggestion 代理内部写入 | `ai_reply_decision_logs` | 与自动回复安全审计相关。 |

这些接口需要事务、幂等、回滚和压测设计，不作为第一试点。

### 2.3 低风险只读接口

| 候选 | 代表路径 | 主要表 | 评价 |
|---|---|---|---|
| 知识分类列表 | `GET /knowledge-categories` | `knowledge_categories` | 查询简单、只读、已有测试、可按商户隔离，对照 SQLite / PostgreSQL 行为清晰。 |
| 算力套餐列表 | `GET /compute/packages` | `compute_packages` | 只读但属于算力模块，旁边有充值、usage、管理员写入接口。 |
| Agent 状态 | `GET /agent/status` | 无 | 风险低，但不访问数据库，不适合作为数据库试点。 |
| 报表汇总 | `GET /reports/summary` | `douyin_leads`、`sales_staff`、`reply_checks` | 只读但聚合多，存在 N+1 查询，首个试点风险偏高。 |

### 2.4 抖音发送 / 私信 / 自动回复 gate 高风险接口

以下接口和服务本轮只审计、不作为试点：

1. `app/routers/douyin_live_check.py` 中私信发送、资源下载、资源上传相关接口。
2. `app/services/douyin_private_message_send_service.py`。
3. `app/services/douyin_autoreply_gate_service.py`。
4. `app/services/ai_auto_reply_send_service.py`。
5. `app/routers/admin_autoreply_rollout.py`。
6. `app/routers/douyin_autoreply_settings.py`。

原因：它们涉及发送门禁、账号授权、自动回复灰度、审计和真实外部调用，不能作为低风险数据库接入试点。

### 2.5 任务调度 / Local Agent 接口

以下接口和服务也不作为第一试点：

1. `app/routers/wechat_tasks.py`。
2. `app/routers/wechat_auto_detect.py`。
3. `app/routers/lead_notifications.py`。
4. `app/routers/lead_notification_actions.py`。
5. `app/services/wechat_task_service.py`。
6. `app/services/notification_service.py`。

原因：这些链路影响 `task_id` 指定执行、paste_only、read_only、回复检测和状态回写，属于已冻结安全边界内的高风险区域。

### 2.6 NewCar 鉴权 / merchant binding 接口

以下接口不作为第一试点：

1. `app/routers/auth.py`。
2. `app/auth/newcar_client.py`。
3. NewCar external-auth/me、exchange-code、logout 链路。
4. external merchant binding 相关初始化 / provision 逻辑。

原因：NewCar 登录和退出是认证主链路，真实模式依赖上游，不适合在第一个数据库试点中混入。

## 3. 选定第一个试点模块

选定试点：`GET /knowledge-categories`

当前调用链：

```text
- app/routers/knowledge_categories.py
  GET /knowledge-categories
  -> get_request_context_required
  -> require_any_permission(["auto_wechat:ai_agents", "auto_wechat:agent"])
  -> apps.knowledge.services.list_visible_knowledge_categories()
  -> knowledge_categories
```

选择理由：

1. 是真实数据库查询，不是纯内存状态。
2. 当前 POST 创建入口已通过 `_deny_category_management()` 返回 403，试点可以只覆盖 GET。
3. 查询表少，只涉及 `knowledge_categories`。
4. 查询条件清晰：`merchant_id`、`scope_type`、`status`、`deleted_at`。
5. 排序清晰：`sort_order`、`id`。
6. 已有测试 `tests/test_knowledge_categories_api.py` 覆盖 base 分类、商户隔离和缺失商户上下文。
7. 不触发抖音发送、私信发送、自动回复 gate、Local Agent、RAG 检索或 Milvus。
8. 适合后续做 SQLite / PostgreSQL 对照测试。

不选择其它候选的原因：

1. `/reports/summary` 虽然只读，但聚合查询多，并且当前销售维度存在多次 count 查询，首轮会把试点和性能重构混在一起。
2. `/compute/packages` 是低风险只读候选，但同文件相邻接口包含充值、管理员写入和内部 usage 上报，边界更容易被扩大。
3. `/agent/status` 不访问数据库，无法验证 async PostgreSQL repository 设计。
4. `/agents` 涉及智能体 CRUD、预览和 9100 调用，不作为第一试点。

## 4. 试点模块涉及表、字段和查询类型

表：`knowledge_categories`

核心字段：

| 字段 | 用途 | PostgreSQL 建议 |
|---|---|---|
| `id` | 排序和主键 | `BIGSERIAL` 或迁移时保留整型主键 |
| `tenant_id` | 预留租户字段 | `VARCHAR(128)` |
| `merchant_id` | 商户隔离 | `VARCHAR(128)`，merchant 分类必填 |
| `category_key` | 分类稳定标识 | `VARCHAR(128)` |
| `name` | 分类展示名 | `VARCHAR(100)` |
| `scope_type` | `system` / `merchant` | `VARCHAR(20)` |
| `is_base` | 是否 base 分类 | 未来建议转为 `BOOLEAN` |
| `status` | `active` / `disabled` / `deleted` | `VARCHAR(20)` |
| `sort_order` | 列表排序 | `INTEGER` |
| `deleted_at` | 软删除时间 | `TIMESTAMPTZ` |
| `created_at` / `updated_at` | 审计时间 | `TIMESTAMPTZ` |

当前 GET 查询类型：

```text
SELECT *
FROM knowledge_categories
WHERE merchant_id = :merchant_id
  AND scope_type = 'merchant'
  AND status = 'active'
  AND deleted_at IS NULL
ORDER BY sort_order ASC, id ASC
```

响应还会在应用层补充逻辑 base 分类：

```text
category_key=base
name=基础知识
scope_type=system
is_base=true
```

## 5. Async repository 设计

后续 P2-F2 / P2-F3 可新增最小 async PG skeleton，但本轮不实现。

推荐方向：

1. 数据库驱动选择：
   - 首选 `SQLAlchemy async engine + asyncpg`，便于延续现有 SQLAlchemy 模型和迁移路线。
   - 或直接使用 `asyncpg`，但 repository 需要手写 SQL 映射。
2. pool 生命周期：
   - FastAPI startup 初始化 engine / pool。
   - FastAPI shutdown 关闭 engine / pool。
   - 禁止每个请求创建 engine / pool。
3. repository 边界：
   - 新增 `KnowledgeCategoryRepository` 或同等最小文件时，只封装试点查询。
   - service 不关心 SQLite / PostgreSQL 方言。
   - 试点期间通过配置开关显式选择 async PG repository，否则继续走当前 SQLite 同步路径。
4. 请求链路：
   - GET 试点接口可以先在 router/service 层按开关选择 repository。
   - 不改变响应结构。
   - 不改 POST 创建分类入口。

## 6. SQLite 与 PostgreSQL 双运行期策略

当前默认仍是 SQLite：

```text
DATABASE_URL 未配置或为 sqlite://...
-> app/database.py 当前同步 SQLAlchemy Session
-> 现有行为不变
```

试点期 PostgreSQL 必须显式启用：

```text
DATABASE_URL=postgresql+asyncpg://...@postgres:5432/auto_wechat
DB_ASYNC_PG_PILOT_MODULE=knowledge_categories
```

配置名只是后续建议，本轮不新增配置。后续真正实现时必须满足：

1. 未显式启用试点时，继续走 SQLite。
2. PostgreSQL 试点异常不能静默降级为错误数据；应返回明确错误并记录脱敏日志。
3. SQLite 回退能力必须保留到 PostgreSQL 全量切换验收完成。
4. SQLite / PostgreSQL 对照测试必须比较响应结构、排序、商户隔离、空结果和缺失权限行为。

## 7. 事务边界和幂等要求

`GET /knowledge-categories` 当前只读，不需要写事务。

后续若把同模块 POST 恢复为试点写入，必须单独设计：

1. `merchant_id + category_key` 唯一约束。
2. 重复提交返回冲突或幂等复用，不能产生重复分类。
3. `base` 分类仍只读，不允许商户创建。
4. 写入和审计字段必须在一个事务内完成。

本轮不恢复 POST，不改分类创建行为。

## 8. 多租户隔离要求

试点必须继续以后端可信 `RequestContext` 为准：

1. `merchant_id`：只能来自 `RequestContext.merchant_id`。
2. `tenant_id`：当前预留，后续纳入查询时也必须来自可信上下文。
3. `account_open_id`：本试点不涉及；涉及抖音企业号时必须校验账号归属，不能信任前端参数。

禁止把前端传入的 `merchant_id`、`tenant_id`、`account_open_id` 当作可信过滤条件。

## 9. 索引建议

当前模型已有索引：

```text
uk_knowledge_categories_merchant_key(merchant_id, category_key)
idx_knowledge_categories_merchant_status_sort(merchant_id, status, sort_order)
idx_knowledge_categories_merchant_key_status(merchant_id, category_key, status)
```

PostgreSQL 试点建议评估：

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_knowledge_categories_visible
ON knowledge_categories (merchant_id, scope_type, status, sort_order, id)
WHERE deleted_at IS NULL;
```

说明：这是后续 P3 / P4 索引建议，本轮不创建索引、不改迁移。

## 10. QPS600 风险点

QPS600 不能只靠连接池默认值保证，需要后续压测验证。

风险点：

1. 同步 SQLAlchemy Session 不能长期支撑高频 async 请求链路。
2. 每请求创建 engine / pool 会导致连接风暴，必须禁止。
3. 多租户字段缺索引会导致高频列表退化为全表扫描。
4. 报表类接口需要避免 N+1 查询。
5. 发送、RAG、LLM、Milvus、外部 OpenAPI 不得阻塞主请求链路。
6. PostgreSQL statement timeout、连接池大小、慢查询日志和索引需要压测后确定。

## 11. 后续实施分解

### P2-F1：设计

完成本文档，选择 `GET /knowledge-categories` 作为第一个试点模块。

### P2-F2：新增 async PG engine / pool skeleton

目标：

1. 基于 `DATABASE_URL` 和 P2-E pool 配置新增 async engine / pool skeleton。
2. startup 初始化，shutdown 关闭。
3. PostgreSQL 未启用时不影响 SQLite。
4. 不在每请求创建 pool。

### P2-F3：试点 repository

目标：

1. 为 `GET /knowledge-categories` 新增 async PostgreSQL repository。
2. 保留 SQLite 同步旧路径。
3. 不改响应结构。

### P2-F4：试点接口开关

目标：

1. 通过显式配置只让 `GET /knowledge-categories` 使用 async PG repository。
2. 其它 9000 接口继续走 SQLite。
3. 错误日志必须脱敏，不打印完整 `DATABASE_URL`。

### P2-F5：SQLite / PostgreSQL 对照测试

目标：

1. 同一批 synthetic 分类数据写入 SQLite / PostgreSQL。
2. 对照验证响应结构、排序、商户隔离和空库结果。
3. 确认缺少权限、缺少 merchant_id 时行为一致。

## 12. 本轮未执行内容

本轮未执行：

1. 未连接 PostgreSQL。
2. 未切换 9000 到 PostgreSQL。
3. 未改业务 SQL。
4. 未改表结构。
5. 未引入 Alembic。
6. 未跑迁移。
7. 未改 docker-compose。
8. 未改 9100。
9. 未改 Milvus。
10. 未触发 LLM、抖音发送、私信发送或自动回复 gate。
11. 未写入真实 URI、token 或 password。
