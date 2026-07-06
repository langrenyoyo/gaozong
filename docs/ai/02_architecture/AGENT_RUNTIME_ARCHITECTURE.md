# AGENT_RUNTIME_ARCHITECTURE.md

> 本文档用于固化抖音AI小高客服的未来 Agent Runtime 架构预留。当前阶段只做设计建议，不安装依赖、不实现 LangChain、不改业务代码。

更新时间：2026-06-18

------

## 1. 为什么提前预留 Agent Runtime

客户二期很可能要求在 AI 回复前后增加可调用工具，例如：

- 查询商户库存后再进行智能回复。
- 查询车型、价格、金融方案。
- 查询客户历史跟进记录。
- 查询商户知识库。
- 根据违禁词 / 合规规则过滤回复。

如果一期把 AI 回复逻辑写死在单一路径中，二期接入工具时会大面积重构 `reply_decision_service`、上下文传递、日志审计、商户隔离和降级策略。提前预留 Agent Runtime 抽象，可以在不替换现有 LLM 主链路的前提下，为二期工具编排留出稳定扩展点。

------

## 2. 推荐落点

Agent Runtime 推荐放在：

```text
apps/xg_douyin_ai_cs/services/
```

原因：

1. `9100 apps/xg_douyin_ai_cs` 当前已经负责抖音AI客服、RAG、LLM 回复建议，是未来智能体编排的自然边界。
2. `9000` 主服务负责 webhook、线索、销售、微信任务、回复检测和后台业务 API，不应直接引入 LangChain 依赖。
3. `19000` Local Agent 是本机微信执行代理，不是 LLM Agent，不应承载 AI 工具编排。
4. 如果 `9000` 后续需要 AI 回复能力，应通过 HTTP 调用 `9100`，不直接依赖 LangChain 或 9100 内部实现。

------

## 3. 建议目录结构

```text
apps/xg_douyin_ai_cs/services/agent_runtime.py
apps/xg_douyin_ai_cs/services/agent_context.py
apps/xg_douyin_ai_cs/services/agent_tools/
  __init__.py
  base.py
  registry.py
  mock_tools.py
  inventory_search_tool.py
  vehicle_price_tool.py
  customer_history_tool.py
  merchant_kb_tool.py
  compliance_check_tool.py
```

目录职责：

- `agent_context.py`：定义 Agent 运行上下文，统一传递 `merchant_id`、`douyin_account_id`、`agent_id`、会话、用户消息、知识库命中等信息。
- `agent_runtime.py`：定义 `AgentRuntimeFacade`，对业务层暴露稳定接口。
- `agent_tools/base.py`：定义工具适配器基类。
- `agent_tools/registry.py`：定义工具注册、启停判断和调用入口。
- `agent_tools/mock_tools.py`：一期预留 mock tool，不调用真实库存、支付或外部系统。
- 其他 tool 文件：二期逐步落地真实只读工具。

------

## 4. AgentRuntimeFacade 接口草案

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentContext:
    merchant_id: str
    douyin_account_id: str
    agent_id: str | None
    conversation_id: str
    user_open_id: str | None
    user_message: str
    conversation_messages: list[dict[str, Any]]
    retrieved_knowledge: list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass
class AgentRuntimeResult:
    reply_text: str
    manual_required: bool
    used_tools: list[str]
    tool_errors: list[dict[str, Any]]
    fallback_used: bool
    audit_metadata: dict[str, Any]


class AgentRuntimeFacade:
    def suggest_reply(self, context: AgentContext) -> AgentRuntimeResult:
        """生成回复建议。工具失败时必须可降级到普通 AI 回复。"""
        raise NotImplementedError
```

上下文传递原则：

1. `merchant_id` 必须来自可信登录态、账号绑定或服务端查询结果，不能由前端任意传入后直接信任。
2. `douyin_account_id` 必须用于隔离抖音账号、会话、知识库和工具权限。
3. `agent_id` 用于选择智能体配置、提示词、知识库和工具启停策略。
4. 所有 tool 调用必须携带完整 `AgentContext`，禁止只传用户文本。

------

## 5. ToolRegistry 接口草案

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolRunResult:
    ok: bool
    data: Any
    error_code: str | None = None
    error_message: str | None = None
    elapsed_ms: int | None = None


class BaseToolAdapter:
    name: str

    def is_enabled(self, context: AgentContext) -> bool:
        """判断当前商户、抖音账号、智能体是否允许使用该工具。"""
        raise NotImplementedError

    def run(self, context: AgentContext, args: dict[str, Any]) -> ToolRunResult:
        """执行工具。默认要求只读、限时、可审计。"""
        raise NotImplementedError


class ToolRegistry:
    def get_enabled_tools(self, context: AgentContext) -> list[BaseToolAdapter]:
        raise NotImplementedError

    def run_tool(
        self,
        name: str,
        context: AgentContext,
        args: dict[str, Any],
    ) -> ToolRunResult:
        raise NotImplementedError
```

二期预留工具：

- `inventory_search_tool`：查询商户库存。
- `vehicle_price_tool`：查询车辆价格 / 报价。
- `customer_history_tool`：查询客户历史消息和跟进记录。
- `merchant_kb_tool`：查询商户知识库。
- `compliance_check_tool`：违禁词 / 合规检查。

------

## 6. 一期接入原则

一期只做架构预留和 mock tool 设计，不改变现有 AI 回复主链路。

必须遵守：

1. 不安装 LangChain。
2. 不替换 `OpenAICompatibleClient`。
3. 不替换 `ArkEmbeddingClient`。
4. 不重构现有 `reply_decision_service` 主链路。
5. 不真实调用库存、支付、外部系统。
6. 只预留可选分支和 mock tool 设计。
7. 默认关闭：

```env
XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED=false
```

一期最小接入范围建议：

1. 只在文档和接口设计中定义 `AgentRuntimeFacade`、`AgentContext`、`ToolRegistry`。
2. 若后续进入代码阶段，先增加关闭态配置和 mock tool 骨架。
3. `reply_decision_service` 保持现有 `RAG → OpenAICompatibleClient.chat → ReplySuggestionResponse(auto_send=false)` 主链路。
4. Agent Runtime 分支失败或关闭时，必须回退到普通 AI 回复建议。

------

## 7. 二期扩展原则

二期接入 LangChain 或其他编排层时，必须保持业务层不直接依赖具体框架。

原则：

1. LangChain 只是可选编排层，不是业务层强依赖。
2. 所有 tools 必须只读优先。
3. 所有 tools 必须强制 `merchant_id` / `douyin_account_id` / `agent_id` 隔离。
4. tool 超时必须降级到普通 AI 回复建议。
5. tool 调用必须记录审计日志，包括工具名、上下文摘要、耗时、结果状态、错误码和降级状态。
6. 合规检查失败时 `manual_required=true`，不允许自动发送。
7. tool 输出只能作为回复生成的参考材料，不能直接无校验地发送给客户。
8. 外部系统调用必须有明确产品确认和接口契约，不允许默认真实调用库存、支付、金融或其他外部系统。

------

## 8. 主要风险点

| 风险 | 说明 | 建议 |
|------|------|------|
| 依赖冲突 | LangChain 及其传递依赖可能影响现有 9100 运行环境。 | 一期不安装；二期单独评估依赖锁定和容器隔离。 |
| 商户隔离 | tool 如果缺少 `merchant_id` 过滤，可能跨商户读取数据。 | `AgentContext` 强制携带商户、账号、智能体上下文。 |
| tool 超时 | 库存、价格、历史记录查询可能拖慢回复建议。 | 每个 tool 设置超时和降级策略。 |
| 幻觉 | LLM 可能把 tool 结果扩大解释。 | tool 结果结构化传入，回复前做合规和事实约束。 |
| 权限越权 | 前端传入 agent_id 或 account_id 可能被伪造。 | 服务端根据登录态和绑定关系解析可信上下文。 |
| 日志审计 | 无审计会导致工具调用不可追溯。 | 记录 tool 调用审计日志并做敏感信息脱敏。 |
| 自动发送风险 | AI 回复未经人工确认可能触发投诉或合规问题。 | 当前 `auto_send=false`；合规失败强制 `manual_required=true`。 |
