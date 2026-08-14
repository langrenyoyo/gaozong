# 模块链路说明（M01-M07）

> 状态：G1 BASELINE（2026-08-14，CODE_SOURCE_BASE=88235b5）
> 用途：7 个业务模块的统一「链路说明」入口，支撑 G3 模块验真与独立验收。
> 每份 CHAIN.md 含 14 节：Responsibility / User Entrypoints / Frontend Entrypoints / Backend API Entrypoints / Core Services / Data Ownership / Async-Worker / External Dependencies / Cross-Module Calls / Auth-Merchant Boundary / Compatibility / Legacy Candidates / Known Unknowns / Future G3 Acceptance Boundary。
> 文件级归属事实以 `docs/architecture/code-map/code_index.yaml`（canonical）为准，本目录为模块级链路骨架。

| 模块 | 名称 | 链路说明 | 核心域 |
|---|---|---|---|
| M01 | 抖音AI小高客服 | [CHAIN.md](M01/CHAIN.md) | 抖音私信 AI 客服、自动回复、9100 RAG/LLM 子应用、发送 gate |
| M02 | AI小高线索 | [CHAIN.md](M02/CHAIN.md) | 线索全生命周期、contact 领域共享、通知派单、回访/反馈 |
| M03 | AI小高智能体 | [CHAIN.md](M03/CHAIN.md) | agent 配置/绑定、知识分类与训练、能力中心网关 |
| M04 | AI小高微信助手 | [CHAIN.md](M04/CHAIN.md) | 19000 Local Agent、微信任务 claim/lease、日报生成投递 |
| M05 | 小高素材库 | [CHAIN.md](M05/CHAIN.md) | 素材上传/存储/管理/分析（与 M06 共置，BC-02） |
| M06 | AI小高剪辑 | [CHAIN.md](M06/CHAIN.md) | LAS 云端混剪编排、产物轮询（素材库页面域 M05） |
| M07 | AI小高算力 | [CHAIN.md](M07/CHAIN.md) | 计费、余额、幂等扣费（P1 Compute Idempotency CLOSED） |

## Known Unknowns 汇总索引

- U-001：douyin_accounts router M01/M03 边界未冻结（M01 §13）
- U-002：Agent 绑定→Auto Reply / 事实隔离 / Training 隔离门未 staging 补测（M01/M03 §13）
- U-003：9100 训练/反馈自动入库 PG 事务边界 = MIDPOINT（M01 §13）
- U-004：空号反馈追问门禁豁免清单待用户逐项确认（M02 §13）
- U-005：通知/回访真实发送端到端未 staging 双 19000 复核（M02/M04 §13）
- U-006：capability_gateway META 运行时可达性未逐一验证（M03 §13）
- U-007：素材重复审计批量处理未定论（M05 §13）
- U-008：LAS Shot.Empty 故障边界判定（M06 §13，见记忆 las-speech-auto-material-requirements）

> 备注：UNKNOWN 仅指模块级事实未冻结（U-001~U-008 分布登记于各链 §13），与 code_index.yaml 中文件级 owner_type=UNKNOWN（6 个 docs 条目）是两个不同维度。
