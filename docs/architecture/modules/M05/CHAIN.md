# M05 小高素材库 链路说明

> 状态：G1 BASELINE（2026-08-14，基于 CODE_SOURCE_BASE=88235b5 冻结文件地图）
> 用途：M05 模块的链路骨架，支撑 G3 模块验真与独立验收。G1 阶段只登记事实，不展开 G3 验收。

## 1. Responsibility
- 素材库：素材上传/存储/管理/分析，供 AI 剪辑（M06）消费。
- **边界红线**：不负责剪辑执行（归 M06）；与 M06 在同一 router/feature 目录共置（BC-02，MIXED 登记）。
- 素材元数据与文件存储为 M05 域；剪辑任务编排/执行（LAS）为 M06 域。

## 2. User Entrypoints
- 5173 前端「AI剪辑」工作台的素材库页（MaterialLibrary）、LasRemixWorkbench（M06 剪辑工作台，页面域 M05）。
- 素材上传/删除/列表/分析结果查看。

## 3. Frontend Entrypoints
- feature 目录：`frontend/src/features/ai-edit/`（BC-02：M05/M06 共置；MaterialLibrary + LasRemixWorkbench + localApi + api + routes + types）。
- 页面：MaterialLibrary、LasRemixWorkbench。
- API clients：ai-edit/api.ts、ai-edit/localApi.ts（19000 本地旧接口，DEV_ONLY）。
- 状态逻辑测试：features/ai-edit/pages/__status_logic_test__.js（DEV_ONLY 自检）。

## 4. Backend API Entrypoints
- `app/routers/ai_edit.py`：MIXED（BC-02）——M05 素材库 API + M06 剪辑 API 共置。
- material_analysis consumer：M05 素材分析（P3b M05 Reference，0033 migration）。

## 5. Core Services
- `app/services/`：ai_edit_service（BC-02 共置域）、ai_edit_storage（素材存储）、material_analysis（素材分析）。
- 脚本：scripts/audit_phase12_task12_duplicate_materials.py（DEV_ONLY 去重审计）。

## 6. Data Ownership
- 9000 库表：ai_edit_materials、material_analysis 相关表（0033）。
- 被其他模块读写：M06 读取素材产物做混剪；M07 计费（material_analysis usage，幂等，P3b M05 0033 PG_RUNTIME_VERIFIED）。

## 7. Async / Worker Chain
- 素材上传 → ai_edit_storage（文件 + 元数据）→ material_analysis（异步分析）→ 分析结果写回 → M06 消费。
- material_analysis 计费：M07 consumer（identity=material_analysis:{id}，进程内无 HTTP hop）。

## 8. External Dependencies
- 对象存储：素材文件存储（本地/可配置）。
- Milvus：素材向量（可选，扩展）。
- 无 LAS 直接依赖（LAS 归 M06）；剪辑触发由 M06 编排。

## 9. Cross-Module Calls
- CALLS：M07（material_analysis 计费）、M06（素材供混剪）。
- READS：无强跨域读。
- COMPAT_FOR：无（ai_edit router 为 MIXED 主 owner M05）。

## 10. Auth / Merchant Boundary
- 权限码：`auto_wechat:ai_edit`（AI剪辑入口权限，承载素材库 + 剪辑工作台）。
- merchant 隔离：素材归属商户校验（PLATFORM-ISO）。
- LAS_API_KEY 前端不持有（TOS/LAS 凭证环境变量注入，M06 侧）。

## 11. Compatibility Layer
- ai_edit router 的 M05/M06 共置区：MIXED 状态（BC-02 section evidence），非单一 owner 选择。
- features/ai-edit/localApi.ts：19000 本地旧接口 client（DEV_ONLY 兼容，LAS 方案后弃用）。

## 12. Legacy Candidates
- 旧本地剪辑执行面（worker/pipeline/stabilizer/9100 规划）：已按 2026-07-31 LAS 方案删除，数据模型 7 表保留复用（非现存代码 Legacy）。
- localApi.ts / build_ai_edit_worker_exe.ps1：DEV_ONLY/LOW，旧执行面遗留（登记 ≠ 可删除）。

## 13. Known Unknowns
- U-007：素材重复审计（task12 duplicate audit）发现的重复素材批量处理未定论。
- 素材文件存储位置/容量在 staging 未复核。
- 剪辑产物归档与素材库的引用关系未完全冻结（M06 边界）。

## 14. Future G3 Acceptance Boundary
- G3 验收应覆盖：素材上传→存储→分析→结果读回；素材归属商户隔离；material_analysis 计费幂等（0033 NO_DOUBLE_CHARGE）；素材供 M06 混剪的引用完整性；`auto_wechat:ai_edit` 权限门。G1 阶段不展开。
