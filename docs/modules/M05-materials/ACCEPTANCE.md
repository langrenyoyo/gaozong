# M05 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| 素材 API/Service 合同（回收站互斥/同 SHA 收敛/跨商户并存/响应不泄露/平台只读） | COVERED | test_phase12_task12_material_api.py |
| 素材分析（人工覆盖优先/AI 快照不可变/表结构冻结） | COVERED | test_phase12_task12_material_analysis.py |
| 云端存储函数存在性 | PARTIAL | test_phase12_task12_material_cloud.py（合同占位测试，TOS 上传主链路未覆盖） |
| 素材 schema/约束（process 唯一/扩展列/purge 配对/同商户 SHA 唯一） | COVERED | test_phase12_task12_material_schema.py |
| TOS 上传端点（upload-tos 真实流程/probe/预签名刷新/复活软删） | MISSING | 无 |
| 方舟多模态分析（analyze_material_async 真实调用/失败态） | MISSING | 无 |
| 软删除引用拦截（被未终态 job 钉住 409） | MISSING | 无 |
| 删除端点 | MISSING | 无 |
| reanalyze 端点 | MISSING | 无 |
| Local Agent 注册端点 | MISSING | 无 |
| M06 素材消费（create_job 校验+pinned_sha256） | PARTIAL | 代码确认（ai_edit_service.py:241-280），无 E2E |
| 商户隔离 | COVERED | 合同测试覆盖跨商户并存/平台只读 |

## E2E 验真结果（2-M05.2 Docker，2026-08-07）

环境：docker compose dev（9000 + SQLite，TOS/Ark 凭证未配置）

| Gate | 域 | 结果 | 证据 |
|---|---|---|---|
| B | Dedup Scope | **PASS** | 同 merchant 同 sha 软删后重注册→reuse（id 不变）；不同 merchant 相同 sha→coexist（id 不同） |
| F | Soft Delete | **PASS** | 无引用素材→delete→deleted_at set + purge_after set + get_material_for_merchant 不可见 |
| G | Referenced Delete | **FAIL → ISSUE-M05-005 HIGH** | active job 引用素材时 soft_delete 未抛 AiEditMaterialInUse（类型不匹配：material_id 字符串 vs AiEditJobMaterial.material_id Integer）；终态后删除 PASS |
| H | M06 Consumption | **PASS** | 跨商户素材不可见 + 同商户素材可见 |
| 专项 | Purge | IMPLEMENTED_DATA_MODEL_ONLY | purge_after 字段存在但无 worker/script/scheduler 执行器 |
| C | Presigned URL | **FAIL → ISSUE-M05-004 HIGH** | tos_presigned_url 临时 HTTPS URL 直接持久化 DB，cloud_storage_key stable key 未写入 |
| A | Upload | ENVIRONMENT_BLOCKED | TOS 凭证未配置 |
| D | Analyze | ENVIRONMENT_BLOCKED | 需方舟多模态 API |
| E | Re-analyze | ENVIRONMENT_BLOCKED | 同 Gate D |

### ISSUE 发现

- **ISSUE-M05-005 HIGH**：soft_delete_material 活动引用检查类型不匹配（material_id 字符串 vs AiEditJobMaterial.material_id Integer），导致被活动 job 引用的素材可被误删
- **ISSUE-M05-004 HIGH**：预签名 URL 持久化到 DB（已在上轮 2-M05.1 口径修正中发现）

### 仍 ENVIRONMENT_BLOCKED

- Gate A（Upload TOS）+ Gate D（Analyze）+ Gate E（Re-analyze）需 TOS/Ark 凭证

**E2E 状态：`M05_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_FIXTURE`**（无 BLOCKER，Gate B/F/H PASS + 专项 IMPLEMENTED_DATA_MODEL_ONLY，Gate G/C FAIL→2 HIGH ISSUE 已登记不阻断 Baseline，Gate A/D/E ENVIRONMENT_BLOCKED）

## E2E 验收清单（待 2-M05.2 补验证）

### DOCKER_TESTABLE
1. 素材列表 + 分页
2. 上传素材（TOS 真实或 mock）
3. 软删除 + 引用拦截（409）
4. 重新分析
5. M06 create_job 校验素材 + pinned_sha256

### EXTERNAL_ENV_REQUIRED
6. TOS 真实上传（需 TOS_ACCESS_KEY/TOS_SECRET_KEY）
7. 方舟多模态分析（需 ARK API key）
8. LAS 预签名 URL 消费（需 LAS 环境，属 M06）

### NOT_APPLICABLE
9. Windows 19000 — M05 不依赖 Local Agent
10. 真实微信 — M05 不依赖微信

---

## M05_BASELINE_CANDIDATE

> 状态：**BASELINE_CANDIDATE**（非 MODULE_BASELINE_APPROVED）
> 代码基线：c26ec227e70d
> 后续补 TOS/Ark 凭证时只补 Gate A/D/E，不重做已验证项

### VERIFIED

- M05 owns AiEditMaterial/Analysis/Process/Template
- SHA-256 幂等去重（merchant scope, reuse + coexist）
- 软删除（deleted_at + purge_after + 不可见）
- M06 消费校验（get_material_for_merchant + pinned_sha256 防漂移）
- 商户隔离（cross-merchant 不可见 + platform 只读）
- Local Agent 注册 ≠ M04 19000（术语区分）
- Purge = IMPLEMENTED_DATA_MODEL_ONLY（字段存在无执行器）

### CODE_VERIFIED

- TOS upload implementation path（服务器中转式，ai_edit.py:224-351）
- Ark multimodal analysis path（material_analysis.py, has_speech/transcript/description/category）
- Re-analysis implementation path

### PENDING_EXTERNAL_INTEGRATION

- Real TOS upload（需 TOS 凭证）
- Real Ark analysis（需方舟 API key）
- Real Ark re-analysis（需方舟 API key）

### NOT_APPLICABLE

- Windows 19000 / 真实微信 / staging webhook

### 冻结路径

TOS/Ark 凭证可用 → 补 Gate A/D/E → `M05_MODULE_BASELINE_APPROVED`
