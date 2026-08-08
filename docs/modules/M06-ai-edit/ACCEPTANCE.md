# M06 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| LAS client submit/poll/wait/parse | COVERED | test_las_client.py（4 用例） |
| process_las_job 轮询→终态→归档 | PARTIAL | test_ai_edit_result_delivery.py（32 用例，用 mock artifacts 非 mock LAS client.wait_for_terminal） |
| 临时 URL 不入 storage_key | COVERED | test_ai_edit_result_delivery.py:331,344 + test_independent_ai_edit_attack.py:711 |
| 标题三件套 | COVERED | test_ai_edit_result_delivery.py:251,259,425 |
| 视频标签 | COVERED | test_ai_edit_result_delivery.py:300,440,459 |
| 归档成功/失败→交付态 | COVERED | test_ai_edit_result_delivery.py:90,111,124,133,355,364 |
| 软删除四件套+幂等+TOS失败 | COVERED | test_ai_edit_result_delivery.py:207,219,229,241,404,518,555 |
| 越权（跨商户/无商户/已删/未归档） | COVERED | test_independent_ai_edit_attack.py（17 用例） |
| 下载 token fail-closed | COVERED | test_ai_edit_download_token.py（7 用例） |
| create_las_job 组装参数/submit/写库 | MISSING | 无直接测试 |
| 算力上报（_report_las_compute_usage） | MISSING | 无 LAS→compute 联动测试 |
| 端到端（真实 LAS submit→poll→archive） | MISSING | 全 mock 不触网 |

## E2E 验真结果（2-M06.2 Docker，2026-08-08）

环境：docker compose dev（9000 + SQLite，LAS/TOS/Ark 凭证未配置）

### Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| A Manual Material Contract | **PASS** | AiEditJobMaterial.pinned_sha256 == AiEditMaterial.source_sha256 验证通过 |
| B Material Delete After Pin | **FAIL → ISSUE-M05-005 确认** | active job 引用素材时 soft_delete 未阻断（类型不匹配 IMPACT VERIFIED for Manual/AiEditJobMaterial-backed jobs） |
| C LAS Input URL Provenance | **CODE_VERIFIED + ISSUE-M05-004 影响确认** | LAS video_urls 来自请求体（前端传 tos_presigned_url）；**M05 tos_presigned_url 是临时 URL 持久化到 DB（ISSUE-M05-004），LAS 消费该 URL，过期后 LAS submit 可能失败** → ISSUE-M05-004 影响域扩展到 M06 |
| D LAS Submit | PENDING_EXTERNAL | LAS_API_KEY 未配置 |
| E Terminal Processing | PENDING_EXTERNAL | 依赖 LAS submit；status CHECK APPLICATION_VALIDATION_PENDING |
| F Archive | PENDING_EXTERNAL | 依赖 LAS submit |
| G Download Token | **PASS** | fail-closed（DY_SECRET_KEY 缺失→RuntimeError→安全拒绝） |
| H Delete | **PASS** | succeeded job→delete_las_job→delete_status 流转（operator_id 参数） |
| I Orchestration Recovery | ABSENT + NOT_VERIFIED | Automatic durable worker recovery: ABSENT；Manual recovery: delete_las_job 幂等但无 archive 补偿脚本；Process restart: 无启动恢复逻辑 |

### Gate C 关键发现

LAS 链路消费 M05 的 `tos_presigned_url`（临时 HTTPS URL）作为 LAS submit 的 `video_urls` 输入。这意味着 **ISSUE-M05-004（预签名 URL 持久化到 DB）的影响域扩展到 M06**——如果预签名 URL 过期，LAS submit 会收到过期 URL 导致失败。

### Gate I 结论（REQUIRED-3 定性）

- Automatic durable worker recovery: **ABSENT**（BackgroundTask 非持久化，无 outbox/scheduler，main.py startup 无 LAS 恢复）
- Process restart recovery: **NOT_VERIFIED**（无启动恢复逻辑，job 停留 processing 需人工查 las_task_id 重跑）
- Manual/ops recovery: **LIMITED**（delete_las_job 幂等可重跑，但无 archive 补偿脚本）

### 仍 PENDING_EXTERNAL

- Gate D/F（LAS submit + archive）需 LAS_API_KEY + TOS 凭证
- Gate E（Terminal Processing）依赖 LAS submit 成功

**E2E 状态：`M06_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_EXTERNAL`**（无 BLOCKER，Gate A/G/H PASS + C CODE_VERIFIED + I 定性完成，Gate B 确认 ISSUE-M05-005，Gate D/E/F PENDING_EXTERNAL）

## E2E 验收清单（待 2-M06.2 补验证）

### DOCKER_TESTABLE
1. 创建 LAS job（mock LAS client submit）
2. 状态流转（mock poll → COMPLETED → 归档 → succeeded）
3. 软删除（mock TOS delete）
4. 下载 token 生成+验证
5. 跨商户隔离

### EXTERNAL_ENV_REQUIRED
6. 真实 LAS submit→poll→archive（需 LAS_API_KEY + TOS 凭证）
7. 算力上报真实记录（需 M07 compute 链路）

### NOT_APPLICABLE
8. Windows 19000 — M06 不依赖 Local Agent
9. 真实微信 — M06 不依赖微信
