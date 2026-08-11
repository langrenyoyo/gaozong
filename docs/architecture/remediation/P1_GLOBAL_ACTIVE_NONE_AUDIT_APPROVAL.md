# P1 GLOBAL ACTIVE NONE AUDIT — 独立审批报告

> 审批窗口：`P1-GLOBAL-ACTIVE-NONE-AUDIT-1`（独立审批，非审计窗口自述）
> 审查对象：`docs/architecture/remediation/P1_GLOBAL_ACTIVE_NONE_AUDIT.md`
> Git baseline：`eea9824`
> 审批日期：2026-08-11
> 性质：READ ONLY 审批（未改业务代码、未改迁移、未写 canonical DB、未 commit）
> 裁定：`APPROVED_FAILED_FINDING`

---

## 0. Technical Decision

```
GLOBAL ACTIVE NONE AUDIT = FAILED   ✅ 独立确认成立

F-1: TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = OPEN / P1 BLOCKER
F-2: dev_only /api/compute/internal/usage 丢 key = DORMANT（非阻断，future hardening）

P1: COMPUTE-IDEMPOTENCY-001 = OPEN
    TECHNICAL_CLOSURE = BLOCKED_BY_F1
Final PostgreSQL Concurrent Closure = BLOCKED / NOT AUTHORIZED
```

核心问题："当前代码是否存在一个在正常 9000 生产应用中注册、可通过正式鉴权调用、会触发 LLM 计费、但无法构造 Business Event Identity，从而最终以 `idempotency_key=None` 进入 compute core 的路径？"

**独立答案：YES。** Trusted Reply-Suggestion Proxy（`app/routers/douyin_ai_cs_proxy.py:230`）满足全部条件。

本窗口未采信审计窗口自述，已独立重新枚举、分类、追踪调用链。独立枚举总数 = 审计枚举总数 = 15，差异为零。F-1 静态链每一段均经当前代码事实复核。审计报告核心结论正确，无核心错误，无非核心事实修正需要。

---

## 1. Independent Call-Site Inventory

核心唯一事实源：`apps/compute/services.py:615 def record_usage`。两条汇入路径：
- 路径 A（9100→9000 HTTP）：9100 `_report_*` → `ComputeUsageClient().report_usage`（`apps/xg_douyin_ai_cs/services/compute_usage_client.py:199`）→ `POST /internal/compute/usage`（`app/routers/compute.py:459`）→ `record_usage`。
- 路径 B（9000 进程内）：`app/*` 服务经 re-export shim `app/services/compute_service.py`（`from apps.compute.services import ... record_usage`）→ `record_usage`。

独立枚举结果（与审计 §4 表逐行比对，差异 = 0）：

| # | Call Site | Module | Runtime | identity | None? | 分类 |
|---|-----------|--------|---------|----------|-------|------|
| 1 | `app/services/wechat_task_service.py:512` | M04 | ACTIVE | `wechat_task:{task.id}:result_usage` | 否 | ACTIVE |
| 2 | `app/services/ai_edit_las_service.py:749` | M06 | ACTIVE | `las_job:{job.id}:archive_usage` | 否 | ACTIVE |
| 3 | `reply_decision_service.py:3800`（Auto Reply 分支） | M01 | ACTIVE | `ai_auto_reply_run:{run_id}:{attempt_count}:{stage}` | 否 | ACTIVE |
| 4 | `app/integrations/douyin_webhook.py:1251` | M02 | ACTIVE | `webhook_event:{event.id}:lead_usage` | 否 | ACTIVE |
| 5 | `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py:281` | Phase9 | ACTIVE | `return_visit_run:{run_id}:judge` | 否 | ACTIVE |
| 6 | `apps/xg_douyin_ai_cs/services/daily_report_summary_service.py:152` | M03 | ACTIVE | `daily_report_generation:{generation_id}:summary` | 否 | ACTIVE |
| 7 | `reply_decision_service.py:3810`（Preview 分支） | M01 | ACTIVE | `ai_preview_execution:{preview_execution_id}:{stage}` | 否 | ACTIVE |
| 8 | `app/services/material_analysis.py:267` | M05 | ACTIVE | `material_analysis_execution:{execution_id}:ark_analysis` | 否 | ACTIVE |
| 9 | `apps/xg_douyin_ai_cs/services/knowledge_training_service.py:555` | M03 | ACTIVE | `knowledge_training_execution:{execution_id}:ask` | 否 | ACTIVE |
| 10 | `apps/xg_douyin_ai_cs/rag/repository.py:504` | M03 | ACTIVE | `rag_search_execution:{execution_id}:{embedding_stage}` | 否 | ACTIVE |
| 11 | `apps/xg_douyin_ai_cs/rag/repository.py:501` | M03 | ACTIVE | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | 否 | ACTIVE |
| **12** | **`app/routers/douyin_ai_cs_proxy.py:365`** | **M03 proxy** | **ACTIVE** | **payload 无 identity → 9100 全 None** | **是 ★** | **ACTIVE / None-bearing** |
| 13 | `app/routers/compute.py:482`（透传点） | M07 | ACTIVE（传输层） | 透传 `payload.idempotency_key` | 否 | 传输层 |
| 14 | `apps/compute/routers.py:362`（dev_only） | M07 | dev_only | handler 未传 key | 是（若调用） | DORMANT |
| 15 | `packages/clients/compute_client.py:114` | legacy | TEST_ONLY | 签名无 key 参数 | 是（若调用） | TEST_ONLY/LEGACY |

**独立枚举总数 = 15**；审计枚举总数 = 15；差异 = 0。不存在审计未列出的第 16 个调用点。

口径说明：审计"11 ACTIVE consumer"按 identity namespace 计数，非物理 call site。`reply_decision_service.py:3814` 一个物理调用点拆为 #3（auto_reply_run）+ #7（preview_execution）两 namespace；`repository.py:523` 一个物理调用点拆为 #10（query）+ #11（ingest）两 namespace。物理调用点 = 9（4 直接 record_usage + 5 ComputeUsageClient.report_usage）+ #12 proxy + #13 传输层/客户端 + #14 dev_only + #15 legacy = 15。

非计费 surface 已排除：`app/services/return_visit_run_service.py:269/:363`（ReturnVisitRun run 级 sha256 去重键）、`app/routers/health.py:44`（readiness 列名清单）、`app/models.py:1147`（ReturnVisitRun 列定义）、`migrations/.../0030_compute_idempotency.py`（建列迁移）。

---

## 2. Trusted Proxy Registration

- 文件：`app/routers/douyin_ai_cs_proxy.py`
- router prefix：`/integrations/douyin-ai-cs`（:40 `APIRouter(prefix="/integrations/douyin-ai-cs", ...)`）
- HTTP method / path：`POST /conversations/{conversation_id}/reply-suggestion`（:230 `@router.post(...)`）
- 完整路径：`POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`
- handler：`create_reply_suggestion_proxy`（:231）
- **app include 位置**：`app/main.py:139 app.include_router(douyin_ai_cs_proxy.router)` ✅ 主 9000 生产 app 挂载（非文件存在即认 ACTIVE，已确认正式挂载）
- 环境门禁：无。该 route 无 env guard 关闭。
- feature flag：无。该 route 无 feature flag 关闭。
- 鉴权依赖：`Depends(get_request_context_required)`（:234）✅
- 权限依赖：`require_permission("auto_wechat:douyin_ai_cs")(context)`（:238）✅

确认：route 正式注册、正式鉴权、无任何关闭门禁。非"文件存在即认 ACTIVE"，而是 main.py:139 挂载事实。

---

## 3. ACTIVE Classification

冻结 ACTIVE 定义（本 P1 已冻结）："当前正式部署中的业务 API、worker、scheduler、service 可以在正常运行条件下到达并产生 compute charge。"

逐层核验 Trusted Proxy：

| 维度 | 结果 | 证据 |
|------|------|------|
| REGISTERED | ✅ | main.py:139 挂载 |
| EXTERNALLY REACHABLE | ✅ | HTTP POST route |
| AUTHENTICATED | ✅ | get_request_context_required + require_permission("auto_wechat:douyin_ai_cs") |
| CHARGE-CAPABLE | ✅ | suggest_reply→9100 LLM→_report_llm_usage→record_usage（见 §14） |
| 无禁用门禁 | ✅ | 无 env/feature flag hard-coded fail closed |
| 文档正式用途 | ✅ | 见 §5 |

**不存在使该 route 实际无法进入 charge path 的硬条件**：无 feature permanently disabled、无 unreachable auth policy、无 environment excluded、无 route never mounted、无 hard-coded fail closed、无 service client disabled。

裁定：**ACTIVE**。不为符合审计窗口 FAILED 而硬判——独立查明无任何关闭门禁，ACTIVE 分类成立。

IN-REPO CALLER COUNT = 0（见 §6），但依冻结定义，"无当前 frontend caller"不能单独证明 inactive（外部客户端、桌面端、历史前端版本、直接 HTTP 消费均可能调用）。正式注册 + 鉴权 + 文档正式用途 + 无禁用门禁 → ACTIVE。未把"无 repo frontend caller"偷偷改成 DORMANT。

---

## 4. Business Documentation Evidence

独立查找原始 current-facing 文档（非 archive）。多份当前正式文档描述该 exact route 并标注为正式业务 contract：

| 文档 | 行号 | 描述 exact route | 标注"正式工作台必须使用" | 当前正式 |
|------|------|------------------|--------------------------|----------|
| `docs/ai/04_interface_contracts/09_INTERFACE_CONTRACT_AUTO_WECHAT.md` | 1497（§16.3） | 是 | 是（"前端生成回复建议时调用 9000，不直接调用 9100 正式链路"） | 是（P0-API-1，非 archive，无"非当前事实"标注） |
| `docs/ai/06_rag/P1_RAG_PRODUCTIZATION_GAP_REVIEW.md` | 56/201/248 | 是 | 是（:56"正式工作台使用 getTrustedReplySuggestion()"，:248"商户 AI 客服消费入口…校验 auto_wechat:douyin_ai_cs，由 9000 注入可信上下文"） | 是（2026-07-02，非 archive） |
| `docs/ai/03_data_and_migration/PHASE_3F_DOUYIN_CS_MIGRATION_REVIEW.md` | 299/477 | 是 | 是（:299"工作台主链路使用的是 getTrustedReplySuggestion()"） | 是（2026-06-22，非 archive） |
| `docs/ai/05_acceptance/P6_DY_AI_CS_STRUCTURED_REPLY_ACCEPTANCE.md` | 39 | 是 | 调用链图"前端工作台 → getTrustedReplySuggestion() → 9000 reply-suggestion proxy" | 是（注：文档断言与代码事实"0 调用点"矛盾，见 §6） |

前端定义处注释：`frontend/src/api/douyinAiCsClient.ts:757` `// 内部调试专用：正式商户侧工作台必须使用 getTrustedReplySuggestion 走 9000 可信代理。`

证据性质：RUNTIME REACHABILITY SUPPORTING EVIDENCE。不替代代码调用链，但支持 ACTIVE 分类。多份当前正式文档（含接口契约 09 与多份 acceptance）一致将其描述为正式商户侧工作台主链路。

---

## 5. In-Repo Caller Search

字面量搜索结果：
- `getTrustedReplySuggestion`（标识符）：3 处，全部在 `frontend/`：`:757` 注释、`:766` 定义、`features/douyin-cs/api.ts:17` re-export。
- `getTrustedReplySuggestion(`（带括号实际调用）：1 处，即 `douyinAiCsClient.ts:766` 的函数定义本身。

```
IN-REPO CALLER COUNT = 0
```

补充事实：
- `frontend/src/features/douyin-cs/components/ReplyDecisionPanel.tsx` 仅 import 类型 `ReplySuggestionResponse`/`ReplySourceChunk`，未 import `getTrustedReplySuggestion`。
- 文档 `P1_FE_E2E_ACCEPTANCE.md:130` 声称"`generateReply()` 只调用 `getTrustedReplySuggestion()`"，但 `generateReply` 在 `frontend/` 内 0 匹配——该函数当前不存在。即文档断言超前于代码实现。
- `packages/`、`scripts/`、`apps/`（除 9100 服务自身）下 Trusted Proxy 客户端调用方 = 0。

依 §3 ACTIVE 定义，"无 repo frontend caller"不证明 inactive。ACTIVE 分类维持。

---

## 6. Proxy Payload Identity Audit

handler payload（`douyin_ai_cs_proxy.py:316-362`）字段清单：`tenant_id`、`account_id`、`douyin_account_id`、`merchant_id`、`agent_id`、`agent_config{...}`、`latest_message`、`max_history_messages`、`conversation_history`、`customer_memory`、`direct_llm_policy`、`forbidden_words`、`**_build_preview_contact_state(...)`。

独立确认 payload **不含**：`run_id`、`attempt_count`、`preview_execution_id`、`search_execution_id`、`material execution identity`、任何其他 durable billing identity 字段。

对比已验证 Preview 路径：`app/routers/agents.py:312`（_create_preview_execution durable commit 后透传 preview_execution_id，0034 PG_RUNTIME_VERIFIED）——proxy payload 与之相比缺失全部三个 identity 字段。

目标确认：Trusted Proxy payload 不提供任何已识别的 durable billing execution identity。✅ 成立。

---

## 7. 9100 Identity Resolution

完整读取 `_report_llm_usage`（`reply_decision_service.py:3763-3832`），identity 选择逻辑：

```python
# :3786-3789
run_id = getattr(request, "run_id", None)               # ReplySuggestionRequest.run_id 默认 None（schemas.py:178）
attempt_count = getattr(request, "attempt_count", None) # :179 默认 None
preview_execution_id = getattr(request, "preview_execution_id", None)  # :184 默认 None
idempotency_key = None
# :3790 Auto Reply 完整 identity 分支
if run_id is not None and attempt_count is not None:
    if preview_execution_id is not None:  # :3792 mixed → warning, 退 None（不构造畸形 key）
        ...
    else:  # :3799
        idempotency_key = f"ai_auto_reply_run:{run_id}:{attempt_count}:{llm_call_stage}"
# :3801 partial identity → warning, 退 None
elif run_id is not None or attempt_count is not None:
    ...（不构造 key）
# :3807 Preview 独立分支
elif preview_execution_id is not None:
    idempotency_key = f"ai_preview_execution:{preview_execution_id}:{llm_call_stage}"
# :3811 run_id=None AND attempt_count=None AND preview_execution_id=None → legacy 兼容路径，不传 key（idempotency_key 保持 None）
```

Proxy 路径下三个 identity 字段全 None（payload 不含 → ReplySuggestionRequest 反序列化取字段默认值 None）→ 不进 :3790/:3801/:3807 任一分支 → `idempotency_key` 保持初始 `None`（:3789）→ :3811 legacy 兼容路径 → :3814 `ComputeUsageClient().report_usage(idempotency_key=None, ...)`。

关键：**全 None 不会导致 skip usage report**。唯一 skip 条件是 :3783-3784 `if not request.merchant_id: return`；proxy payload 含 `merchant_id`（:320，且 ComputeUsageRequest 有 `_strip_merchant_id` 非空校验），故不 skip。全 None 直接走 report_usage → legacy 裸扣。

9100 调用链入口确认：9100 route `/douyin/reply-suggestion`（`apps/xg_douyin_ai_cs/routers/ai_reply.py:21`）/ `/douyin/conversations/{conversation_id}/reply-suggestion`（:33）→ `:29/:41 build_reply_suggestion(conversation_id, request)` → `reply_decision_service.py:628 def build_reply_suggestion` → 内部分支调用 `_build_llm_reply(...)`（:568/:590/:614）→ `_build_llm_reply`（:981）内 `:1160 _report_llm_usage(llm_call_stage="primary")` / `:1236 retry_combined`。每条 LLM 成功分支均触发 `_report_llm_usage`。

---

## 8. Partial / Mixed Guard Behavior

§12 关键问题：partial/mixed identity guard 对 F-1 是 FAIL CLOSED 还是允许全 None 作为 legacy path？

- partial（:3801-3806）：`run_id`/`attempt_count` 一有一无 → warning + **退 None**（不构造畸形 key）。
- mixed（:3792-3798）：Auto Reply + Preview 同时 → warning + **退 None**。
- 全 None（:3811）：不进任何 guard → `idempotency_key` 保持 None → 直接传入 report_usage。

结论：partial/mixed guard 的效果是**把"畸形 key"降级为"None legacy 裸扣"**，而非阻断计费。全 None 分支无任何 guard，直接裸扣。**guard 不 fail closed**——它把问题降级到 legacy None 路径，最终允许全 None 作为 legacy billing。

若全 None 实际导致 skip usage report，F-1 不成立。但代码事实是 :3814 无条件调用 `ComputeUsageClient().report_usage(idempotency_key=None)`（merchant_id 非空前提下），**不 skip**。F-1 核心证据成立。

---

## 9. ComputeUsageClient Propagation

`apps/xg_douyin_ai_cs/services/compute_usage_client.py:199 def report_usage`：
- 签名：`idempotency_key: str | None = None`（:215）
- :260 `payload["idempotency_key"] = idempotency_key` → 原样放入 HTTP body。

确认：`idempotency_key=None` 是**显式发送**（JSON body 中 `"idempotency_key": null`），非字段省略，非 client 内部转成其他值。None 经 HTTP 透传到 9000。

---

## 10. 9000 Internal Usage Request Model

`app/schemas.py:1377 class ComputeUsageRequest(BaseModel)`：
- `idempotency_key: Optional[str] = Field(None, max_length=255, description="幂等身份（None 走旧逻辑裸扣）")`（:1404）✅ Optional + default None
- `model_config = {"extra": "forbid", "protected_namespaces": ()}`（:1415）
- validator：`_strip_merchant_id`（:1406-1413）仅校验 merchant_id 非空白；**无 validator 拒绝 None idempotency_key**。

`app/routers/compute.py:459-483` handler：
- :463 `Depends(_require_internal)`（X-Internal-Token 校验，9100 持有 token）
- :482 `idempotency_key=payload.idempotency_key` 透传到 record_usage ✅

确认：None 能过 Pydantic/API 校验，不被拒绝，透传不丢。✅

---

## 11. record_usage None Behavior

`apps/compute/services.py:615 def record_usage`：
- :631 签名 `idempotency_key: str | None = None` ✅ 允许 None
- :681 `if idempotency_key:` → None falsy → **跳过幂等块**（:679-769 整段不执行）
- :772 `if idempotency_key is None:` → True → :773-776 打 warning
- :777-800 legacy 路径：`get_or_create_account` + `_write_transaction(...)`（调用未传 idempotency_key，等价 NULL）+ `db.commit()` → **裸扣，写 ComputeTransaction**

行为分类：
- A. reject ❌
- B. skip charge ❌
- C. generate fallback identity ❌
- D. proceed with normal non-idempotent charge ✅ **成立**

只有 D 或等价行为，F-1 才成立。代码事实 = D。`record_usage(None)` 不拒绝、不跳过、不生成 fallback identity，直接 legacy 裸扣并 commit。F-1 的 record_usage 行为前提满足。

补充：空串 `""` → :681 falsy 跳过幂等块 → :772 `is None` False → 不打 warning → 静默 legacy 裸扣（审计 §7.3 准确）。whitespace-only → :681 truthy 进幂等块 → :682 strip 变空串 → 以空串 INSERT（partial/empty identity 风险，但无 ACTIVE consumer 产生 whitespace-only key）。

---

## 12. PostgreSQL NULL Semantics

`app/models.py:927-998 class ComputeTransaction`（`__tablename__ = "compute_transactions"`，:937）：
- :997 `idempotency_key = Column(String(255), nullable=True, ...)` ✅ nullable
- :941 `UniqueConstraint("merchant_id", "idempotency_key", name="uk_compute_transactions_merchant_idempotency")` ✅ 复合 UNIQUE
- :940 注释："P1 COMPUTE-IDEMPOTENCY-001：幂等唯一约束（nullable NULL 不参与约束，兼容阶段1）"
- **非 partial unique index**（无 `postgresql_where` / WHERE 子句），是普通复合 UNIQUE constraint。

Alembic 迁移 `migrations/postgres/auto_wechat/versions/0030_compute_idempotency.py`：
- :23-27 `op.add_column("compute_transactions", sa.Column("idempotency_key", sa.String(255), nullable=True, ...))`
- :36-40 `op.create_unique_constraint("uk_compute_transactions_merchant_idempotency", "compute_transactions", ["merchant_id", "idempotency_key"])`（普通 UNIQUE，无 partial）
- docstring: "nullable 列，backward-compatible：旧调用不传 idempotency_key 走旧逻辑（NULL 不参与唯一约束）。"

PostgreSQL NULL 语义（SQL 标准）：UNIQUE constraint 中 NULL 视为 distinct（不相等），含 NULL 的复合键行不与任何其它行冲突。

**当前 schema 判定**：多行 `idempotency_key=NULL`（即使 `merchant_id` 相同）**可以并存**，不触发唯一约束冲突。唯一约束仅阻止 `idempotency_key` 非 NULL 时的 `(merchant_id, idempotency_key)` 重复。

这是 non-idempotent risk 的重要组成部分：F-1 路径每次调用都产生 `idempotency_key=NULL` 的新 ComputeTransaction 行，无去重，**同一 business event 的 retry 会重复扣费**。

---

## 13. Full F-1 Chain

独立形成的完整静态链（每段引用当前代码事实）：

```
1. 9000 Trusted Reply-Suggestion Proxy
   app/routers/douyin_ai_cs_proxy.py:230 @router.post("/conversations/{conversation_id}/reply-suggestion")
   handler create_reply_suggestion_proxy (:231)
   app/main.py:139 app.include_router(douyin_ai_cs_proxy.router) — 主 9000 生产 app 挂载
   prefix /integrations/douyin-ai-cs (:40)
   → authenticated business route
       Depends(get_request_context_required) (:234)
       require_permission("auto_wechat:douyin_ai_cs") (:238)

2. payload lacks durable billing identity
   douyin_ai_cs_proxy.py:316-362 — payload 不含 run_id/attempt_count/preview_execution_id
   对比 agents.py:312 Preview 路径设 preview_execution_id

3. 9000→9100 reply suggestion
   douyin_ai_cs_proxy.py:365 get_xg_douyin_ai_cs_client().suggest_reply(context, conversation_id, request=payload)
   app/services/xg_douyin_ai_cs_client.py:52 def suggest_reply (:65 self._post_json("/douyin/reply-suggestion", payload))

4. 9100 路由入口
   apps/xg_douyin_ai_cs/routers/ai_reply.py:21 /douyin/reply-suggestion (:33 /douyin/conversations/{id}/reply-suggestion)
   :29/:41 build_reply_suggestion(conversation_id, request)
   reply_decision_service.py:628 def build_reply_suggestion → _build_llm_reply (:568/:590/:614)

5. LLM billable call
   _build_llm_reply (:981) → client.chat(...) (LLM 计费调用)

6. usage report + identity resolution = None
   reply_decision_service.py:1160 _report_llm_usage(request=request, llm_call_stage="primary")
                              :1236 retry_combined
   _report_llm_usage (:3763):3786-3788 getattr 全 None (ReplySuggestionRequest :178/:179/:184 默认 None)
                              :3811 legacy 兼容路径 → idempotency_key 保持 None (:3789)

7. ComputeUsageClient
   :3814 ComputeUsageClient().report_usage(idempotency_key=None, ...)
   compute_usage_client.py:199 def report_usage :260 payload["idempotency_key"]=None
   → HTTP body "idempotency_key": null

8. 9000 internal compute usage
   app/routers/compute.py:459 POST /internal/compute/usage (internal_router prefix /internal + :458 /compute/usage)
   :463 _require_internal (X-Internal-Token)
   :482 idempotency_key=payload.idempotency_key (None)
   ComputeUsageRequest.idempotency_key Optional default None (app/schemas.py:1404) — None 过校验

9. record_usage(idempotency_key=None)
   apps/compute/services.py:615 :631 签名允许 None
   :681 if idempotency_key: None falsy → 跳过幂等块
   :772 if idempotency_key is None: → warning
   :777-800 legacy 路径 get_or_create_account + _write_transaction + db.commit() → 裸扣

10. PostgreSQL ComputeTransaction(idempotency_key=NULL)
    app/models.py:997 nullable=True
    app/models.py:941 UniqueConstraint(merchant_id, idempotency_key) — 复合 UNIQUE 非 partial
    PostgreSQL: NULL 不参与唯一约束 → 多行 NULL 可并存 → 同一 business event retry 重复扣费
```

完整链成立。F-1 真实成立。

---

## 14. Runtime Probe / Evidence Level

本审批窗口未执行 runtime probe。

未执行原因：
1. 审批窗口定位为 READ ONLY 独立审查（不 commit、不改业务代码、不写 canonical DB）；runtime e2e 属执行窗口工作。
2. runtime probe 需启动 9000+9100 双 FastAPI 进程 + 隔离 PG 容器 + mock 外部 LLM provider + 触发鉴权 token + 真实 proxy/suggest_reply/usage-reporting/record_usage/PG 路径，环境成本不低。
3. 静态契约完整且无歧义：每一段均有当前代码事实，identity 默认值、guard 行为、core None 路径、PG NULL 语义均经独立复核，无需要 runtime 探测才能消除的歧义。

证据等级（依 §20 准确标注）：

```
F-1 ACTIVE REACHABILITY = ROUTE_VERIFIED + CODE_VERIFIED
  (main.py:139 挂载 + 鉴权/权限门禁 + 完整调用链代码事实)

NULL BILLING PATH = CODE_VERIFIED
  (payload→9100 identity resolution None→ComputeUsageClient→9000 record_usage→legacy 裸扣→PG NULL)

F-1 PG_RUNTIME_VERIFIED = 未达成（未在隔离 PG 实际产生 NULL ComputeTransaction 行）
```

不写 `PG_RUNTIME_VERIFIED`。若后续返工窗口需 runtime 印证，须在隔离 PG 执行，mock 仅限最终外部 LLM provider，不得 mock proxy handler / identity resolver / usage reporting / compute client / record_usage / PG ledger（§19）。若 runtime probe 自然产生 `ComputeTransaction.idempotency_key IS NULL`，则 F-1 升级为最强证据；但本审批不依赖之。

---

## 15. F-2 Classification

独立核验 `apps/compute/routers.py` 的 `/api/compute/internal/usage`：
- :88 `router = APIRouter(prefix="/api/compute", tags=["小高算力"])`
- :353 `@router.post("/internal/usage", ...)` → 完整路径 `/api/compute/internal/usage`
- :362-377 handler 调 `compute_service.record_usage(...)` **未传 `idempotency_key=payload.idempotency_key`** ✅ 丢失（对比 `app/routers/compute.py:482`）

挂载核验：
- 该 router 仅经 `apps/compute/router.py:4-9` → `apps/compute/main.py:5-14`（`create_app()` → `create_capability_app(META, router)`，模块级 `app`）挂载 → compute-service @9205。
- 主 9000 生产 app（`app/main.py`）挂载 `compute.router`（:153，prefix `/compute`）、`compute.admin_router`（:154，prefix `/admin`）、`compute.internal_router`（:155，prefix `/internal`）——全部来自 `app/routers/compute.py`，其 `report_usage` 路径 = `/internal/compute/usage`（:458），且 :482 透传 idempotency_key。
- `app/main.py` import 列表（:20-57）无 `apps.compute`。主 9000 app **不**挂载 `apps.compute.routers`。✅

RUNTIME_ENTRYPOINTS.md：compute-service（9205）标 `dev_only`（§八 docker-compose.dev.yml 表，:279）；生产 `docker-compose.yml` 表（:261-266）不含 compute-service。

潜在 client `packages/clients/compute_client.py:26 class ComputeClient` / `:114 report_usage`：
- 签名无 `idempotency_key` 参数。
- POST `/api/compute/internal/usage`（指向 9205）。
- 生产代码 import 数量 = 0；唯一引用 = `tests/test_compute_client.py:8`。

F-2 分类：**DORMANT**（dev_only + test-only client）。准确，非阻断。

```
F-2 = DORMANT
NON-BLOCKING FUTURE HARDENING
```

若 compute-service 转生产，须先补 idempotency_key 透传（`apps/compute/routers.py:362` 加 `idempotency_key=payload.idempotency_key`）+ `ComputeClient.report_usage` 签名补 idempotency_key。属 future governance，**不纳入本次 F-1 remediation scope**。

---

## 16. 11/11 Consumer Reconciliation

11 条冻结 charge path identity 与当前代码逐一核对，identity 构造点与冻结 contract 一致（与审计 §6 一致）：

| # | 冻结 identity | 代码位置 | 一致 |
|---|---------------|----------|------|
| 1 | `wechat_task:{task.id}:result_usage` | wechat_task_service.py:512 | ✅ |
| 2 | `las_job:{job.id}:archive_usage` | ai_edit_las_service.py:749 | ✅ |
| 3 | `ai_auto_reply_run:{run_id}:{attempt_count}:{stage}` | reply_decision_service.py:3800 | ✅ |
| 4 | `webhook_event:{event.id}:lead_usage` | douyin_webhook.py:1251 | ✅ |
| 5 | `return_visit_run:{run_id}:judge` | return_visit_judge_service.py:281 | ✅ |
| 6 | `daily_report_generation:{generation_id}:summary` | daily_report_summary_service.py:152 | ✅ |
| 7 | `ai_preview_execution:{preview_execution_id}:{stage}` | reply_decision_service.py:3810 | ✅ |
| 8 | `material_analysis_execution:{execution_id}:ark_analysis` | material_analysis.py:267 | ✅ |
| 9 | `knowledge_training_execution:{execution_id}:ask` | knowledge_training_service.py:555 | ✅ |
| 10 | `rag_search_execution:{execution_id}:{embedding_stage}` | repository.py:504 | ✅ |
| 11 | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | repository.py:501 | ✅ |

11/11 identity-bearing。本审批未发现任一 consumer 退化为 None。未重新跑全部 consumer PG E2E（本审批为 None Audit，非 consumer 重验证）。

注意：11 条枚举遗漏第 12 条 ACTIVE 路径（Trusted Proxy），该路径不在冻结 11 条表内却产生 compute charge——这是本次审计的发现，F-1 成立。

---

## 17. Global Metrics

```
TOTAL compute-related call sites = 15
ACTIVE consumers with valid identity = 11
ACTIVE None paths = 1（#12 Trusted Reply-Suggestion Proxy）
DORMANT None paths = 1（#14 dev_only compute-service route）
UNKNOWN = 0
TEST_ONLY/LEGACY = 1（#15 legacy ComputeClient）
传输层 = 1（#13 /internal/compute/usage 透传，非独立 consumer）
```

UNKNOWN = 0：#12 已判 ACTIVE（非 UNKNOWN）；#14/#15 已判 DORMANT/TEST_ONLY 并举证。F-1 结论不依赖任何 UNKNOWN 分类。

---

## 18. Canonical Ledger Interpretation

审计报告 canonical local `auto_wechat` 库 `compute_transactions = 0 行`。本审批窗口未重复查询（避免不必要 canonical 交互），接受审计 §13 的只读 SELECT 事实，并准确描述：

```
NO CURRENT CANONICAL HISTORICAL LEDGER EVIDENCE
```

这**不等于**"NULL problem does not exist"。本次 FAILED 来自 current code reachability（F-1 静态链成立），非历史 ledger 行观测。canonical 本地库 0 行仅因开发库未跑计费业务；若 #12 路径在生产被调用，将新增 `idempotency_key=NULL` 的 CURRENT ACTIVE 行——这是 FAILED 的运行时投射，未在本库观测仅因本库未跑该业务。

本审批全程未在 canonical `auto_wechat@5432` 制造任何 NULL ledger row（未执行 runtime probe，未写 canonical DB）。

---

## 19. P1 Blocking Status

```
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = PENDING → BLOCKED_BY_F1
F-1: TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY = OPEN / P1 BLOCKER
```

F-1 修复目标首先是：
```
same Business Event → stable identity → no double charge
```

不自动扩大为 full request recovery orchestration（除非设计证明二者不可分）。core None 兼容（`record_usage(None)` legacy 裸扣）可能服务 legacy/compatibility callers，本窗口**不**决定 `record_usage(None)` globally reject——F-1 优先是 ACTIVE consumer 必须 become identity-bearing，core hardening 是否另做由后续设计判断（§35）。

11/11 Consumer Migration Complete、PG Verification、Application Role Permission、Fresh Bootstrap Principal Reproducibility 等既有基线不受本审计影响，维持 COMPLETE/VERIFIED。

---

## 20. Final Concurrent Gate Status

```
Final PostgreSQL Concurrent Closure Gate = BLOCKED / NOT AUTHORIZED
```

直至 F-1 修复并重新审计（或其增量）确认 ACTIVE None = 0，方可进入 Final Concurrent Closure。

本窗口未启动 RB-10、未启动 Final Concurrent work、未宣布 P1 Closed。

---

## 21. Required Next Design Questions

下一窗口 **P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-DESIGN** 至少回答：

1. Trusted Reply-Suggestion 的业务事件是什么？
2. durable identity 在哪里创建？
3. 创建时点在 LLM 前还是后？
4. retry 如何复用同一 identity？
5. 是否需要新 execution table？
6. 是否可安全复用现有 Preview execution 模型（`ai_preview_execution` namespace + `_create_preview_execution`）？
7. 前端/API contract 是否需要新增 execution id？
8. compatibility caller 怎么办？
9. failed request 是否仍保留 execution？
10. same event replay 如何验证只扣一次？

**禁止用随机 request UUID / timestamp / random UUID / hash(payload) 充当 Business Event Identity**——retry-safe identity ≠ unique-per-request identity。若每次 HTTP retry 生成新 UUID，同一 business event 会产生不同 idempotency key，仍 double charge。返工必须从业务事件语义开始，而非字符串生成。

本审批窗口不回答以上问题（§31/§33）。

---

## 22. Verdict

```
APPROVED_FAILED_FINDING

GLOBAL_ACTIVE_NONE_AUDIT = FAILED

F-1: TRUSTED_REPLY_SUGGESTION_PROXY_NONE_IDENTITY
    = OPEN / P1 BLOCKER
    ACTIVE REACHABILITY = ROUTE_VERIFIED + CODE_VERIFIED
    NULL BILLING PATH = CODE_VERIFIED
    PG_RUNTIME_VERIFIED = 未达成（未执行 runtime probe，static contract 审批）

F-2: dev_only /api/compute/internal/usage 丢 idempotency_key
    = DORMANT（NON-BLOCKING FUTURE HARDENING）

独立枚举 vs 审计枚举：15 vs 15，差异 0
ACTIVE None / Empty / Partial Identity：1（#12）
UNKNOWN：0
```

F-1 独立确认真实成立：Trusted Reply-Suggestion Proxy 在主 9000 生产 app 注册（main.py:139）、鉴权可达（require_permission）、文档标注正式业务路径、无任何关闭门禁、调用链可达 LLM 计费且 payload 不含任何 durable billing identity → 9100 全 None → idempotency_key=None → core legacy 裸扣 → PostgreSQL `idempotency_key=NULL` ComputeTransaction（NULL 不参与唯一约束，多行可并存，retry 重复扣费）。

审计报告核心结论正确、行号引用准确、F-2 DORMANT 分类正确、PG NULL 语义描述准确、11/11 reconciliation 准确。本审批未发现核心错误，亦无非核心事实修正需要。

---

## 23. 提交下一阶段候选

```
P1-F1-TRUSTED-REPLY-SUGGESTION-IDEMPOTENCY-DESIGN
```

本窗口未自行：修改 proxy payload、新建 execution table、复用 Preview identity、修改 compute core、开始 Final Concurrent Closure、RB-10、push、宣布 P1 Closed。

---

## 附录：审批纪律确认

- NO BUSINESS CODE CHANGE：未改任何业务代码。
- NO MIGRATION CHANGE：未改迁移。
- READ ONLY AUDIT：未写 canonical DB，未在 canonical `auto_wechat@5432` 制造 NULL ledger row。
- 未 commit、未 push、未宣布 P1 Closed、未启动 RB-10、未启动 Final Concurrent Closure。
- 本窗口唯一新增产物：`docs/architecture/remediation/P1_GLOBAL_ACTIVE_NONE_AUDIT_APPROVAL.md`。
- 审计报告 `P1_GLOBAL_ACTIVE_NONE_AUDIT.md` 未被修改（无核心错误、无非核心修正需要）。
```
