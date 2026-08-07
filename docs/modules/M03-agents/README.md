# M03 AI小高智能体

> 状态：`M03_CURRENT_REALITY_VERIFIED_PENDING_E2E`
> source_baseline: c26ec227e70d | 验真日期: 2026-08-07

## M03 是什么

AI小高智能体是商户配置抖音私信 AI 客服的核心管理模块。商户在此创建/编辑智能体、配置 Prompt 和知识库绑定、绑定抖音企业号，并预览回复效果。

## 对商户提供什么

| 能力 | 入口 | 状态 |
|---|---|---|
| 智能体列表 | GET /agents | ACTIVE |
| 新建智能体 | POST /agents（弹窗） | ACTIVE |
| 编辑智能体 | PUT /agents/{id}（弹窗） | ACTIVE |
| 删除智能体 | DELETE /agents/{id}（硬删除） | ACTIVE |
| 停用/启用 | 后端支持但前端无控件 | UNKNOWN（代码存在不可达） |
| 知识库绑定 | GET/PUT /agents/{id}/knowledge-categories | ACTIVE |
| AI回复预览 | POST /agents/preview | ACTIVE |
| 抖音账号绑定 | 通过 M01 binding service | ACTIVE |
| 训练对话 | POST /agents/{id}/training-chat | ACTIVE（不调 LLM，纯本地拼字符串） |

## Owner

- **数据 Owner**：`ai_agents` / `agent_knowledge_categories` / `douyin_account_agent_bindings` 三表，M03 物理且业务 Owner
- **`knowledge_categories`**：物理在 M03 主库，业务 Owner 是 M05/9100 RAG

## 主要入口

- 前端：`/agents`（navId `ai-agents`），`SuperMerchantAgent` 组件，权限 `auto_wechat:douyin_ai_cs`
- 后端：`app/routers/agents.py`（9 端点，prefix=/agents）
- 注意：`app/routers/agent.py`（prefix=/agent 单数）是 Local Agent 心跳状态，**与 M03 无关**

## 主要依赖

- → M01（runtime）：preview 调 9100 suggest_reply（`agents.py:272`）
- → M01（contract/payload）：agent_config 随 HTTP payload 传入 9100
- → M05/RAG：经 `agent_knowledge_categories` 绑定 category_key，9100 检索
- → auth/商户隔离/数据库：平台公共底座

## 当前状态

ACTIVE。CRUD 完备，商户隔离严密，preview 不触发真实发送。存在 3 处 agent_config 重复组装逻辑（解耦候选）。super_admin 回复建议路径可绕过商户绑定校验（ISSUE）。9100 集成测试和 super_admin bypass 测试 MISSING。
