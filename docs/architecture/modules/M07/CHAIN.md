# M07 AI小高算力 链路说明

> 状态：G1 BASELINE（2026-08-14，基于 CODE_SOURCE_BASE=88235b5 冻结文件地图）
> 用途：M07 模块的链路骨架，支撑 G3 模块验真与独立验收。G1 阶段只登记事实，不展开 G3 验收。

## 1. Responsibility
- 算力计费：usage 记录、余额、幂等扣费、充值、查询（compute / admin / internal 三 router）。
- **边界红线**：不负责业务动作本身（客服/剪辑/素材归各自模块）；计费必须幂等（NO_DOUBLE_CHARGE），idempotency_key 唯一约束在 PG 生效（NULL 不参与唯一约束 → F-1 修复）。
- P1 Compute Idempotency = CLOSED（COMMIT 1d7f1f5，Final Concurrent Closure VERIFIED）。

## 2. User Entrypoints
- 5173 前端「算力中心」：ComputeCenter、SuperComputeConfig。
- 商户查看余额/用量/充值；管理员配置计费。

## 3. Frontend Entrypoints
- feature 目录：`frontend/src/features/compute/`（ComputeCenter、SuperComputeConfig、api.ts）。
- 页面：ComputeCenter、SuperComputeConfig。
- API clients：compute。

## 4. Backend API Entrypoints
- `app/routers/compute.py`：compute（商户 usage/余额）+ admin（管理）+ internal（内部上报，dev_only F-2 DORMANT）。
- 子应用 `apps/compute/`：main/router/routers/service/services/schema（M07 独立子应用）。
- 兼容入口：app/services/compute_service.py（COMPAT-012，LEGACY-012 调用方兼容）。

## 5. Core Services
- 9000：app/services/compute_service.py（COMPAT 兼容入口）；apps/compute/services/（核心实现，含 atomic UPDATE...RETURNING 余额写入，FC-F1 Candidate B）。
- apps/compute/：service.py、services.py、schema.py、schemas.py、dependencies.py。

## 6. Data Ownership
- 9000 库表：compute_transactions（idempotency_key 唯一约束）、compute_balances、compute_accounts、usage 相关。
- M07 Core：record_usage + DB migration 0030 + atomic ownership + IntegrityError replay/conflict。
- 被其他模块上报：M01（RAG/LLM usage）、M02（return_visit/preview）、M03（training）、M05（material_analysis）、M06（ai_edit/preview）。

## 7. Async / Worker Chain
- 业务模块 → compute consumer（M07 identity 键，如 rag_search_execution:{id}:{primary|fallback_embedding}、ai_preview_execution:{id}:{stage}、material_analysis:{id}）→ record_usage（原子）→ 余额扣减（UPDATE...RETURNING）→ 幂等冲突处理（IntegrityError replay / same-identity return）。
- 无独立 worker；同步扣费 + outbox 不参与计费链路。

## 8. External Dependencies
- PostgreSQL：计费事务唯一约束（0030 migration；NULL idempotency_key 不参与唯一 → 已 F-1 修复）。
- 无外部计费服务；余额数据源为 PG（非 SQLite）。

## 9. Cross-Module Calls
- RECEIVES：M01/M02/M03/M05/M06 全部计费上报（11 consumer 迁移完成，见 P1 Checkpoint 11/11）。
- PROVIDES：余额/用量/账单查询给商户与前端。
- COMPAT_FOR：app/services/compute_service.py 兼容旧调用方（COMPAT-012）。

## 10. Auth / Merchant Boundary
- 权限码：`auto_wechat:compute`（商户）、`auto_wechat:compute_admin`（管理）、internal token（服务端）。
- 商户隔离：balance/transaction 归属校验（PLATFORM-ISO）；余额门禁真实路径（0034 PREVIEW 双 HTTP hop）。

## 11. Compatibility Layer
- COMPAT-012 compute_service：LEGACY-012 兼容入口，removal_prerequisite=全部调用方迁移到 apps/compute/services。
- F-2 dev_only `/api/compute/internal/usage`：DORMANT（丢 idempotency_key，无 ACTIVE 触发）。

## 12. Legacy Candidates
- LEGACY-012 compute_service：COMPAT（非可删）。
- SQLite 旧计费路径：已被 PG 0030 替代（LEGACY）。

## 13. Known Unknowns
- 余额扣减与并发上限在生产 RUNTIME_UNKNOWN（staging/prod app-role GRANT 未落地 → CR-4 staging/prod 侧属独立部署审批）。
- compute markup / metering 配置（SuperComputeConfig）的完整计费规则矩阵未在 G1 冻结。
- 7 REQUEST_RECOVERY_GAP / RB-10 cleanup：保留非 RESOLVED（CLOSED 时记录）。

## 14. Future G3 Acceptance Boundary
- G3 验收应覆盖：11 consumer 全量计费幂等（NO_DOUBLE_CHARGE / DISTINCT_EVENT / STAGE_SEPARATION）；并发扣费原子性（FC-3/FC-R1/FC-R2 场景）；余额门禁；商户隔离越权；internal 接口 fail-closed；COMPAT-012 兼容验证。G1 阶段不展开。
