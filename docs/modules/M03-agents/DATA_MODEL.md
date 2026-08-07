# M03 数据模型

> source_baseline: c26ec227e70d

## M03 拥有的表

### ai_agents（OWNER: M03 物理+业务）

定义：`app/models.py:802-833`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK, 自增 | |
| agent_id | String(64), 唯一 | 业务 ID `agent_{uuid4().hex[:16]}` |
| merchant_id | String(128), 非空 | 可信商户 ID（从 RequestContext 取，非前端传入） |
| name | String | 智能体名称 |
| avatar_seed / avatar_url | String | 头像 |
| prompt | Text | **商户自定义 Prompt** |
| knowledge_base_text | Text | **普通文本知识库** |
| store_address | String | 门店地址（迁移 0019） |
| store_phone | String | 门店电话 |
| store_wechat | String | 门店微信号 |
| business_hours | String | 营业时间 |
| sales_cities | String | 销售城市范围 |
| sales_brands | String | 销售汽车品牌 |
| purchase_cities | String | 收车城市范围 |
| purchase_brands | String | 收车汽车品牌 |
| after_hours_reply | Text | 销售下班留资回复 |
| vehicle_condition_reply | Text | 顾客问车况回复 |
| appraiser_off_hours_reply | Text | 评估师下班留资回复 |
| status | String | active/disabled/deleted |
| created_at / updated_at | DateTime | |

**关键事实**：AiAgent 表无 `tenant_id`（与 AgentKnowledgeCategory/KnowledgeCategory 不同），无 `enabled` 字段（用 `status`）。

### agent_knowledge_categories（OWNER: M03）

定义：`app/models.py:836-867`

Agent↔知识分类手动绑定。通过 `(merchant_id, agent_id, category_key)` 三元组绑定，`category_key` 指向 9100 RAG 分类稳定标识。

### douyin_account_agent_bindings（OWNER: M03）

定义：`app/models.py:424-447`

9000 权威抖音企业号↔AI 智能体绑定。一期一个企业号只绑定一个默认智能体（`is_default`）。

| 字段 | 说明 |
|---|---|
| merchant_id / tenant_id | 商户隔离 |
| account_open_id | 抖音企业号 open_id |
| agent_id | 绑定的智能体 |
| is_default | 默认绑定 |
| status | active/unbound/invalid/deleted |

## M03 消费但非 Owner 的表

### knowledge_categories（物理 M03 主库，业务 M05/9100 RAG）

定义：`app/models.py:870-903`

comment 标注"9000 知识分类主数据表"。表定义在 `app/models.py`（共享），但业务读写由 9100 categories 路由 `apps/xg_douyin_ai_cs/routers/categories.py` 负责。

**M03 仅作为统一建表宿主，业务 Owner 是 M05/9100 RAG。**

## 读写关系汇总

| 表 | M03 读写 | 其他模块读写 |
|---|---|---|
| ai_agents | OWNER（create/update/delete/query） | M01 auto-reply 读 `binding.agent`；M01 preview 读 payload 草稿 |
| agent_knowledge_categories | OWNER（bind/unbind/replace/list） | 无 |
| douyin_account_agent_bindings | OWNER（bind/unbind/validate） | M01 auto-reply 读 `binding.agent` |
| knowledge_categories | 读（ensure_category_usable_for_merchant 校验） | M05/9100 OWNER（读写分类主数据） |

## 商户隔离条件

所有表均含 `merchant_id`。service 层经 `require_context_merchant(context)` 从可信 RequestContext 取 merchant_id，查询/更新/删除均按 merchant_id 过滤。跨商户访问返回 404（get_agent）或错误码（binding 校验）。
