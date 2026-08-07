# 模块依赖矩阵

> 基于 1A.1 SYSTEM_MAP + 1A.2 CODE_INDEX + 1A.3 RUNTIME_ENTRYPOINTS 三份已冻结事实交叉印证（commit c26ec227e70d）。
> 不从目录猜依赖，每格附 file:line 证据。
> Lifecycle 正式定性见 1A.5，本步只标依赖关系。

## 依赖类型标记

| 标记 | 类型 | 含义 |
|---|---|---|
| R | runtime call | 模块 A 运行时调用模块 B 的服务（HTTP/API/函数） |
| D | data access | 模块 A 读写模块 B 的数据表 |
| E | event/task | 模块 A 触发模块 B 的任务/事件 |
| S | shared implementation | 共用 router/feature 目录/代码（解耦候选，非正式业务依赖） |
| X | external integration | 经外部系统间接依赖 |

方向：`→`（行依赖列）、`←`（列依赖行）、`↔`（双向）。行=依赖方，列=被依赖方。

---

## 7×7 模块依赖矩阵

```
       M01    M02    M03    M04    M05    M06    M07
M01     -     D→     X←     -      -      -      R→
M02    D←      -     R→     D→     -      -      -
M03    R→     -       -     -      -      -      -
M04     -     D→     -      -      -      -      -
M05     -      -     -      -       -     S→     -
M06     -      -     -      -     D→      -     D→
M07     -      -     -      -      -      -       -
```

### 每格证据

| 格 | 关系 | 类型 | 方向 | 证据 |
|---|---|---|---|---|
| M01→M02 | webhook upsert DouyinLead + recover_contact_valid | D | M01 writes M02 data | `app/integrations/douyin_webhook.py:678` upsert_lead_from_webhook、`:1194` recover_contact_valid |
| M01→M02 | 客服工作台读 customer_profiles | D | M01 reads M02 data | `app/services/douyin_workbench_conversation_service.py:28` load_customer_profile |
| M01→M07 | compute_usage_client HTTP 上报算力消耗 | R | M01 calls M07 | `apps/xg_douyin_ai_cs/services/compute_usage_client.py:172,199` → `app/routers/compute.py:458` |
| M01←M03 | agent_config 随 HTTP payload 传入（非 M01 直查 M03 库） | X | M03→M01 via payload | `apps/.../reply_decision_service.py:832` request.agent_config |
| M02→M03 | 线索/客服读智能体配置（webhook 解析绑定智能体） | R | M02 calls M03 | webhook 解析绑定智能体；agent_config 经 payload |
| M02→M04 | webhook 新建线索后建 notify_sales WechatTask | D | M02 writes M04 data | `app/integrations/douyin_webhook.py:929,1030`（auto_notify_disabled 当前禁用自动建） |
| M04→M02 | agent_write_back_reply / record_manual_reply 更新 ReplyCheck+DouyinLead | D | M04 writes M02 data | `app/services/wechat_ui_reply_service.py:332`、`app/services/reply_checker.py:15` |
| M05→M06 | 共用 ai_edit.py router 和 features/ai-edit 目录 | S | shared | `app/routers/ai_edit.py`（materials + jobs 共用）、`frontend/src/features/ai-edit/`（解耦候选） |
| M06→M05 | create_job 校验并绑定 AiEditMaterial | D | M06 reads M05 data | `app/services/ai_edit_service.py:256-265` |
| M06→M07 | LAS 成功后同进程调 record_usage | D | M06 calls M07 | `app/services/ai_edit_las_service.py:735-746` → `app/services/compute_service.py:7` |
| M03→M01 | router 预览调 9100 suggest_reply | R | M03 calls M01 | `app/routers/agents.py:272` |

### 重点区分（1A.2 已发现，1A.4 深化）

**M01↔M03**：实为 **M03→M01 单向** runtime（`agents.py:272` suggest_reply）+ M01 消费 M03 的 agent_config（经 payload，**非 M01 直查 M03 库**，记 X← 而非 R←）。**非双向业务依赖**——M01 不主动调 M03。

**M02↔M04**：data 双向读写，但各自单向维护：
- M02→M04：webhook 建 notify_sales WechatTask（`douyin_webhook.py:929`，当前 auto_notify_disabled）
- M04→M02：回写检测结果更新 ReplyCheck/DouyinLead（`wechat_ui_reply_service.py:332`）

**M05↔M06**：**shared_implementation**（共用 router + feature 目录），**解耦候选非正式业务依赖**。M06→M05 有 data 读取（校验素材），但 M05 不依赖 M06。

**M07**：非孤立。被 M01（runtime HTTP 上报）+ M06（data 同进程 record_usage）消费，自身无主动上游依赖。M03 的算力消耗经 M03→M01→M07 间接上报，**M03 不直连 M07**。

---

## 公共底座被谁依赖

| 公共底座 | 被哪些模块用 | 证据 |
|---|---|---|
| auth/RBAC | M01(admin端点)/M02(leads/admin_contact_invalid)/M04(local_agent_auth)/M07(admin_router) 全模块 | `app/auth/dependencies.py` get_request_context_required；`app/routers/auth.py` |
| 数据库底座 | 全模块（auto_wechat 库 54 表） | `app/database.py` engine/SessionLocal；所有 service db: Session 参数 |
| 发送 gate | M01（自动回复发送闸门） | `app/services/douyin_autoreply_gate_service.py` |
| outbox | M01（自动回复任务持久化） | `app/services/ai_auto_reply_outbox_service.py`；consumers: webhook(_wake_outbox_scheduler) |
| 调度器 | M04(check_scheduler/daily_report)/M01(outbox/return_visit)/M02(contact_invalid_followup) | `app/scheduler/*` + `app/main.py:171` startup |
| 商户隔离 | M01/M02（账号归属校验、可信商户过滤） | `app/services/douyin_merchant_isolation.py` require_owned_account |
| 联系方式提取（领域共享） | M01/M02（客服+线索，非平台基础设施） | `app/services/contact_extractor.py` + `contact_state_service.py` + `customer_profile_service.py` |

---

## 外部系统被谁依赖

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

1. **M01 是依赖中心**：M01→M02(data)、M01→M07(runtime)、M01←M03(runtime/integration)。M01 承担 webhook 入口 + 客服回复 + 算力上报，耦合面最广。
2. **M02 是数据 Owner**：DouyinLead/CustomerProfile/ReplyCheck 等核心表归 M02，M01/M04 均读写 M02 数据。解耦时 M02 数据所有权需先明确。
3. **M05/M06 共用代码是解耦候选**：S 关系（shared_implementation），非正式业务依赖，拆分 router/feature 目录是低风险解耦点。
4. **M07 是纯被消费方**：无主动上游，被 M01(runtime) + M06(data) 消费，适合保持独立。
5. **M04→M02 回写链路**是空号追问三路触发源之一（webhook 块4 + 前端手动 1.4 + 销售回写 1.6）。
