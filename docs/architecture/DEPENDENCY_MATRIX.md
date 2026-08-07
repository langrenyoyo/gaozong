# 模块依赖矩阵

> **Derived from CODE_INDEX.yaml + SYSTEM_MAP.md + RUNTIME_ENTRYPOINTS.md（commit c26ec227e70d）**
> 本文件是分析视图，不是独立机器事实源。事实源是 CODE_INDEX.yaml（dependencies 字段）+ RUNTIME_ENTRYPOINTS.md。
> Lifecycle 正式定性见 1A.5，本步只标依赖关系。

## 矩阵语义

- **行 = source/consumer（依赖方）**，**列 = target/provider（被依赖方）**
- 方向由坐标确定，不用 →/← 箭头，避免"双重方向语义"
- 格内只标依赖类型字母（R/D/X/S/E），证据见 Canonical Edge 列表

## 依赖类型定义

| 标记 | 类型 | 含义 | 当前出现 |
|---|---|---|---|
| R | Runtime Call | A 运行时主动调用 B 的服务（HTTP/function/service call） | 3 |
| D | Data Dependency | A 读写 B 拥有的数据（核心是 Data Ownership） | 5 |
| X | Contract / Payload Dependency | A 依赖 B 定义/产生的数据合同或 payload，非 runtime 调用 | 1 |
| S | Shared Implementation | 共用 router/feature 目录/代码（Implementation Coupling，解耦候选） | 1 |
| E | Event / Task Dependency | A 触发 B 的任务/事件 | 0 |

**Current occurrences: E = 0**。即使当前为 0 也声明，防 VibeCoding 自行发明第六种依赖类型。

---

## Canonical Edge 列表（事实源）

边列表是真正事实，矩阵是视图。统计 Canonical Edge 数量（非非空单元格数量）。同一关系的反向视图不重复计；M02↔M04 是两条独立 edge（各自标注），不是"双向依赖"。

| # | source | target | type | mechanism | reason | evidence |
|---|---|---|---|---|---|---|
| E1 | M01 | M02 | D | direct DB | webhook 入口 upsert DouyinLead + recover_contact_valid | `app/integrations/douyin_webhook.py:678` upsert_lead_from_webhook、`:1194` recover_contact_valid |
| E2 | M01 | M02 | D | service call | 客服工作台读 customer_profiles 档案 | `app/services/douyin_workbench_conversation_service.py:28` load_customer_profile |
| E3 | M01 | M07 | R | HTTP | 9100 compute_usage_client 上报算力消耗到 9000 /internal/compute/usage | `apps/.../compute_usage_client.py:172,199` → `app/routers/compute.py:458` |
| E4 | M03 | M01 | R | HTTP | router 预览调 9100 suggest_reply 回复生成 | `app/routers/agents.py:272` |
| E5 | M01 | M03 | X | payload | 9100 接收 request.agent_config（随 HTTP payload 传入，非 M01 直查 M03 库） | `apps/.../reply_decision_service.py:832` |
| E6 | M02 | M03 | R | service call | 线索/客服读智能体配置（webhook 解析绑定智能体，agent_config 经 payload） | webhook 解析绑定智能体 |
| E7 | M02 | M04 | D | task | webhook 新建线索后建 notify_sales WechatTask 供 M04 执行（Task Contract；当前 auto_notify_disabled） | `app/integrations/douyin_webhook.py:929,1030` |
| E8 | M04 | M02 | D | direct DB | agent_write_back_reply / record_manual_reply 更新 ReplyCheck + DouyinLead（Feedback Contract） | `app/services/wechat_ui_reply_service.py:332`、`app/services/reply_checker.py:15` |
| E9 | M05 | M06 | S | shared code | 共用 ai_edit.py router 和 features/ai-edit 目录（解耦候选） | `app/routers/ai_edit.py`、`frontend/src/features/ai-edit/` |
| E10 | M06 | M05 | D | direct DB | create_job 校验并绑定 AiEditMaterial | `app/services/ai_edit_service.py:256-265` |
| E11 | M06 | M07 | D | service call | LAS 成功后同进程调 record_usage 记 ai_edit 消耗 | `app/services/ai_edit_las_service.py:735-746` → `app/services/compute_service.py:7` |

**Canonical Edge 数量：11**（E 类型 0 条）

### mechanism 列说明

区分耦合程度：
- `direct DB` — 直接读写对方数据表，耦合最深
- `service call` — 同进程函数/服务调用
- `HTTP` — 跨进程 HTTP 调用，边界清晰
- `task` — 经任务表投递，异步解耦
- `payload` — 经请求体数据合同传递，非 runtime 调用
- `shared code` — 共用代码，implementation coupling

---

## 7×7 模块依赖矩阵（视图）

从 Canonical Edge 列表生成。行=source，列=target，格=type。

```
       M01   M02   M03   M04   M05   M06   M07
M01     -     D     X     -     -     -     R
M02     -     -     R     D     -     -     -
M03     R     -     -     -     -     -     -
M04     -     D     -     -     -     -     -
M05     -     -     -     -     -     S     -
M06     -     -     -     -     D     -     D
M07     -     -     -     -     -     -     -
```

### 重点关系澄清

**M01↔M03**（E4 + E5）：实为 **M03→M01 单向 runtime**（E4，agents.py:272 suggest_reply）+ **M01 消费 M03 的 agent_config 经 payload**（E5，X 类型非 R）。**非双向业务依赖**——M01 不主动调 M03。

**M02↔M04**（E7 + E8）：两条独立 edge，不是"双向依赖"：
- E7 M02→M04：Task Contract（webhook 建 WechatTask 供 M04 执行，当前 auto_notify_disabled）
- E8 M04→M02：Feedback Contract（回写检测结果更新 ReplyCheck/DouyinLead）

**M05↔M06**（E9 + E10）：
- E9 M05→M06：S（shared_implementation，共用 router/feature，**解耦候选非正式业务依赖**）
- E10 M06→M05：D（create_job 读 AiEditMaterial 校验）
- M05 不依赖 M06 的业务能力

**M07**：在当前 source_baseline（c26ec227）下，M07 表现为纯 Provider/被消费模块——被 M01（E3，runtime HTTP 上报）+ M06（E11，data 同进程 record_usage）消费，自身无主动上游依赖。M03 的算力消耗经 M03→M01→M07 间接上报，M03 不直连 M07。此结论绑定 source_baseline，不构成永久性结论。

---

## Platform Shared Dependencies（6，跨所有模块的基础设施）

| 公共底座 | 被哪些模块用 | 证据 |
|---|---|---|
| auth / RBAC | 全模块（admin 端点权限校验） | `app/auth/dependencies.py` get_request_context_required；`app/routers/auth.py` |
| 数据库底座 | 全模块（auto_wechat 库 54 表） | `app/database.py` engine/SessionLocal；所有 service db: Session 参数 |
| 发送 gate | M01（自动回复发送闸门） | `app/services/douyin_autoreply_gate_service.py` |
| outbox | M01（自动回复任务持久化） | `app/services/ai_auto_reply_outbox_service.py`；consumers: webhook(_wake_outbox_scheduler) |
| 调度器 | M04(check_scheduler/daily_report)/M01(outbox/return_visit)/M02(contact_invalid_followup) | `app/scheduler/*` + `app/main.py:171` startup |
| 商户隔离 | M01/M02（账号归属校验、可信商户过滤） | `app/services/douyin_merchant_isolation.py` require_owned_account |

---

## Domain Shared Dependencies（1，客户/线索领域共享，非平台基础设施）

| 领域共享能力 | 被哪些模块用 | 证据 |
|---|---|---|
| 联系方式提取 | M01/M02（客服+线索） | `app/services/contact_extractor.py` + `contact_state_service.py` + `customer_profile_service.py` + `contact_completion_resolver.py` + `contact_validity_analyzer.py` + `contact_invalid_followup_service.py` + `douyin_customer_profile_deriver.py` |

**不把联系方式提取归为平台底座**——它是客户/线索领域共享，不是平台基础设施。未来可能出现的客户事实/称呼策略/线索状态等同理归 domain_shared，避免产生巨大 `common/`。

---

## External Systems 被谁依赖

| 外部系统 | 被哪些模块用 | 集成方式 | 证据 |
|---|---|---|---|
| 抖音 GMP | M02（webhook 直收）/M01（OpenAPI 解码下载） | webhook 回调 + 签名调用 | `app/routers/integrations.py:845`；`DY_GMP_SECRET_KEY` config.py:225 |
| Milvus | M01（9100 RAG 向量检索） | 9100 pymilvus | `MILVUS_URI` apps/.../config.py:78；仅向量副本非 metadata 真源 |
| NewCarProject | PLATFORM（auth 全模块登录委托） | 9000 HTTP 代理 | `NEWCAR_AUTH_BASE_URL` config.py:262；`app/routers/auth.py` |
| LAS（火山引擎） | M06（云端混剪） | 9000 组装参数→submit→轮询→存产物 | `LAS_API_KEY` config.py:392；`app/services/ai_edit_las_service.py` |
| TOS（火山引擎） | M05（素材存储）/M06（LAS 产物） | 9000 预签名 | `TOS_ACCESS_KEY` config.py:401；`app/services/ai_edit_storage.py` |
| douyinAPI 8081 | （demo/参考实现，非生产依赖） | — | `DOUYIN_API_BASE_URL` config.py:217 默认值；lifecycle=UNKNOWN |

---

## 依赖治理观察

1. **M01 是依赖中心**：E1/E2(→M02 data)、E3(→M07 runtime)、E4/E5(←M03 runtime/payload)。M01 承担 webhook 入口 + 客服回复 + 算力上报，耦合面最广。
2. **M02 是数据 Owner**：DouyinLead/CustomerProfile/ReplyCheck 等核心表归 M02，M01/M04 均读写 M02 数据。解耦时 M02 数据所有权需先明确。
3. **M05/M06 共用代码是解耦候选**：E9 S 关系（shared_implementation），非正式业务依赖，拆分 router/feature 目录是低风险解耦点。
4. **M07 是纯 Provider**（source_baseline c26ec227 下）：无主动上游，被 M01(E3 runtime) + M06(E11 data) 消费，适合保持独立。
5. **M04→M02 回写链路**（E8 Feedback Contract）是空号追问三路触发源之一（webhook 块4 + 前端手动 1.4 + 销售回写 1.6）。
