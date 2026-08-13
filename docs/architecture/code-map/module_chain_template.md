# <MODULE_ID> 链路说明（模板）

> 状态：DRAFT（G1 模块链路骨架模板）
> 用途：为未来每个业务模块建立统一「链路说明」骨架，支撑 G3 模块验真与独立验收。
> 复制本模板到 `docs/architecture/modules/<module_id>/CHAIN.md` 后按事实填充；禁止在 G1 提前做完整 G3 验收。

## 1. Responsibility
> 一句话职责 + 明确不负责什么（边界红线）。

## 2. User Entrypoints
> 用户可感知的入口（菜单 / 页面 / 外部触发）。

## 3. Frontend Entrypoints
> 前端路由、nav id、feature 目录、页面组件、API client。

## 4. Backend API Entrypoints
> HTTP METHOD + PATH + ROUTER 文件 + 鉴权上下文。

## 5. Core Services
> 核心 service 与领域逻辑文件。

## 6. Data Ownership
> 本模块写入/拥有的表；明确被其他模块读写的表（CROSS_MODULE_DATA_ACCESS）。

## 7. Async / Worker Chain
> producer → storage → consumer → trigger → side effect。

## 8. External Dependencies
> 外部集成（NewCar / Douyin GMP / Milvus / LLM / LAS / TOS / 19000 等），含 AUTH/INPUT/OUTPUT/FAILURE IMPACT。

## 9. Cross-Module Calls
> 本模块 CALLS/READS/WRITES/PUBLISHES/CONSUMES/AUTHORIZES/WRAPS/COMPAT_FOR 谁。

## 10. Auth / Merchant Boundary
> 权限码、merchant/tenant 隔离边界、token 来源。

## 11. Compatibility Layer
> 本模块承担的历史兼容路径（COMPAT_ID / purpose / current caller / replacement / removal prerequisite）。

## 12. Legacy Candidates
> 本模块内的 Legacy Candidate（LEGACY_ID / historical purpose / current references / replacement / evidence / risk / status）。登记 ≠ 可删除。

## 13. Known Unknowns
> 未确认归属/行为的事项：问题、缺什么证据、下一阶段如何验证。

## 14. Future G3 Acceptance Boundary
> G3 阶段本模块的验收边界（验收测试应覆盖哪些链路；G1 阶段不展开）。
