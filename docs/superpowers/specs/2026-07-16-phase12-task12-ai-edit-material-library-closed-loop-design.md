# Phase 12 Task 12 AI 素材库私有闭环增强设计

## 1. 文档状态

| 项目 | 内容 |
|---|---|
| Task-ID | `PHASE12-TASK12-REPLAN-PRIVATE-LIBRARY` |
| Design-Revision | `12-PRIVATE-R1` |
| 设计基线 | `9eea0b74d72bf1db8caba76b1b4bc569bdde4dbe` |
| 所属阶段 | Phase 12 |
| 风险等级 | L3：数据库迁移、商户隔离、文件删除与跨端补偿 |
| 设计状态 | `SPEC_REVIEW_PENDING` |
| 生产验证 | Phase 13 完成后另行审批 |
| 影响组件 | 9000、9100、19000、AI 剪辑 Worker、React 前端 |
| 参考实现 | `E:\work\project\auto_edit`，只读参考，不作为运行时依赖 |

本版设计替代 2026-07-16 批准的“私有素材 / 平台公共 / 回收站”方案。用户已选择“方案 1：兼容退役”：产品只保留当前商户私有素材视图；历史平台素材与删除生命周期字段继续保留在内部数据层，但不再形成用户能力。

旧执行包已归档为 `docs/ai/archive/2026-07-17_Phase12_Task12_平台公共与回收站旧执行包_冻结快照.md`，仅供追溯，禁止继续执行。失效集成提交 `0d0aef1cf236580154a8684c37a9baabe9572628` 不得推送、测试、合并或作为新基线。

## 2. 目标、允许范围与禁止事项

### 2.1 目标

1. 素材库只展示当前登录商户的未删除私有素材。
2. 保留批量导入、自动分析、真实预览、人工确认、增稳和商户私有云端上传。
3. 删除后立即从产品中隐藏，内部保留 7 天，到期后由 9000 协调本地与云端副本清理。
4. 7 天内重导同一文件自动恢复；清理完成后重导同一文件复用原规范素材 ID并重新分析，云端副本仍须用户再次主动上传。
5. 保持全局导航、页面标题栏和“素材库 / 剪辑工作台”切换不变。

### 2.2 允许范围

- 9000 私有素材控制面、分阶段状态、人工确认、商户云端存储与内部清理协调。
- 19000 本机导入、媒体探测、自动分析、增稳、本地预览、云端上传和清理补偿。
- 9100 严格内部多模态语义分析。
- 素材库内容区的桌面与移动布局。
- SQLite/PostgreSQL 双轨迁移和历史数据兼容守卫。
- Task 12 本地、模拟和单入口测试 EXE 验收。

### 2.3 禁止事项

- 不新增、发布、查询或管理平台公共素材。
- 不提供用户回收站、恢复按钮、立即永久删除按钮或对应公共 API。
- 不迁移、不合并、不删除历史 `scope=platform` 记录。
- 不允许模板引用平台素材记录。
- 不修改全局导航栏、`AI小高剪辑` 标题栏、`ModuleTabs` 路径或剪辑工作台既有切换。
- 不恢复已取消的一键过审能力。
- 不新增权限码，继续使用 `auto_wechat:ai_edit`。
- 不让浏览器或 19000 直连 9100，不信任前端自报 `merchant_id`。
- 不建设专业多轨编辑器、向量检索或自动抖音发布。
- 不连接生产数据库、真实宝塔目录或真实付费模型；生产验证留 Phase 13 后审批。

## 3. 当前事实与根因

### 3.1 真实调用链

```text
React 素材库
  -> 9000 GET /ai-edit/materials：读取权威素材 metadata
  -> 127.0.0.1:19000：本机导入、删除和任务执行

19000
  -> Local Agent token 映射可信 merchant_id
  -> 本机商户受管目录和本地清单
  -> 9000 Agent 接口同步素材 metadata 与任务状态

9000
  -> SQLite 开发库 / PostgreSQL 目标库
  -> 后续受控商户云端目录
  -> 后续代理调用 9100 内部分析接口
```

### 3.2 当前缺口

- `app.services.ai_edit_service.list_materials` 当前返回本商户素材与 `scope=platform` 素材，不符合私有单视图。
- 9000 列表固定过滤 `deleted_at IS NULL`，前端却按 `deleted_at` 构造回收站，因此旧回收站必然为空。
- `frontend/src/features/ai-edit/pages/MaterialLibrary.tsx` 仍有三标签和平台范围展示。
- `AiEditMaterialOut`、详情 DTO 和前端类型仍暴露 `scope/deleted_at/purge_after`。
- 当前导入默认写 `analysis_status=pending`，没有完整自动分析状态收敛，前端把 `pending` 错译为“处理中”。
- 云端字段已经存在，但真实流式上传、校验、预览和失败补偿尚未闭合。

### 3.3 已落地但尚未进入主线的证据

Task 12-2 数据迁移基线已在主线落地。迁移硬化候选 `b8d9bbd43d3d01c850541c586892b86bb1147fde` 曾通过独立测试，但不是当前主线祖先；其 ORM、SQLite 0034、PostgreSQL 0015 与精确守卫可作为后续重建候选的参考证据，不能继承原测试结论或直接视为已集成。

## 4. 产品语义

### 4.1 单一私有素材库

- 普通用户与超管看到的素材库都只包含当前可信商户的私有素材。
- 超管身份不获得平台素材查询或管理入口。
- 历史平台素材对所有用户和超管都不可见、不可查询、不可预览、不可用于任务、不可修改、不可删除。
- 系统剪辑模板、字幕样式和处理配置继续保留；这些配置只能描述规则，不能引用 `scope=platform` 的素材 ID 或存储键。

### 4.2 删除

- 活动任务引用存在时删除返回 `409 MATERIAL_REFERENCED_BY_ACTIVE_JOB`。
- 删除接口只有在 9000 权威软删和 19000 本地隐藏都完成后才返回成功；成功后素材立即从 9000 列表、详情、搜索、工作台选择器和 19000 用户列表隐藏。
- 删除不立即删除媒体文件；9000 写内部 `deleted_at/purge_after` 并撤销未终态阶段令牌，7 天内保留本地和云端受管副本。
- 产品不显示回收站，不提供恢复和立即永久删除操作。
- 阻止删除的活动任务定义为“状态不在 `succeeded/completed/failed/cancelled` 终态集合内”的任何任务，包括 `queued/running/review_required/cancel_requested/retry_preparing` 及后续新增非终态。
- 删除确认文案固定为：

```text
删除后素材将立即从素材库隐藏，并在 7 天后清理。期间重新导入同一文件可恢复。
```

“在 7 天后清理”表示到期后进入后台清理资格；19000 离线或云端失败时允许延后完成，但素材始终保持用户不可见，不能伪造 completed。

删除采用 9000 权威先提交：

1. 浏览器调用 19000，19000 先原子写入本地 `pending_delete` 意图，记录素材 ID、SHA-256 和请求时间；pending 记录在本地素材列表中按隐藏处理。
2. 19000 调用 9000 Agent 删除接口。9000 在素材锁内校验商户、生命周期和活动引用，写入首次 `deleted_at/purge_after`；重复调用返回首次时间，不刷新 7 天窗口。
3. 同一事务把 `queued/running` 分析与上传阶段推进 attempt、替换为不可恢复的随机令牌摘要并标记 `failed/MATERIAL_DELETED`，使旧 Worker 回写失效。
4. 9000 成功后，19000 把本地清单标记为 deleted 并删除 pending 意图，随后返回成功。
5. 9000 明确失败时，19000 删除 pending 意图并恢复本地可见；9000 结果未知、响应丢失或 19000 崩溃时保留 pending。19000 启动恢复按 pending 记录重放 9000 幂等删除，确认远端状态后完成本地隐藏。
6. 9000 已成功但本地清单写失败时返回 `500 LOCAL_DELETE_STATE_SYNC_FAILED`；9000 用户列表继续保持隐藏，用户重试或重启恢复只补本地状态，不回滚远端。

不执行“9000 已删除后再回滚为活跃”的反向补偿，避免响应丢失导致删除窗口被刷新或旧 Worker 重新获得写权限。

### 4.3 重复导入与恢复

9000 以 `(merchant_id, source_sha256)` 解析规范素材记录，返回权威 `material_id`。浏览器生成的导入 ID 只可作为本机临时标识，不得成为去重依据。

| 现有状态 | 重导行为 | disposition | 结果 |
|---|---|---|---|
| 不存在 | 创建规范记录 | `created` | 返回新规范 ID并排队分析 |
| 活跃 | 返回既有记录 | `existing` | 同一 `agent_client_id` 可补齐本机副本；其他设备返回 409 |
| 7 天保留期，未领取清理 | 自动恢复 | `restored` | 复用原 ID，清空删除字段，保留同哈希有效结果 |
| `purge_status=preparing` | 拒绝 | 无 | `409 MATERIAL_CLEANUP_IN_PROGRESS` |
| `purge_status=completed` | 作为新素材恢复 | `recreated` | 复用原 ID，清空删除/清理字段，重置存储和阶段状态，自动重新分析；云端上传仍由用户触发 |

`restored` 只允许原 `agent_client_id`；已成功阶段继续复用，删除时被 `MATERIAL_DELETED` 终止的阶段自动领取新 attempt 重新排队。`recreated` 可在 completed 状态下原子转移到当前鉴权设备，并使旧设备的 claim、attempt 和回写全部失效。

`recreated` 不删除历史任务和分析追溯。旧任务继续钉住原 `material_id + source_sha256`；人工确认、当前描述、分类和可用区间全部清空，新分析 attempt 必须在历史最大值上单调递增并生成新版本。`created_at` 保留首次创建时间，`updated_at` 更新为本次重导时间并作为默认列表排序依据。`storage_mode` 重置为 `local_only`，不得自动恢复或上传旧云端对象。

### 4.4 分析与增稳

- 导入成功后自动开始媒体探测、转写、内容分析和稳定性检测。
- 媒体探测、转写、内容分析、稳定性和云端上传分别记录状态、进度、attempt 与稳定失败码。
- `pending/queued` 展示为“待处理”，不能展示为“处理中”；只有真实 `running` 才显示处理中和进度。
- AI 结果允许人工修订；人工确认优先于最新 AI 结果，重新分析不得覆盖人工确认。
- 增稳只在用户主动执行后生成衍生素材，原素材不变；失败不得创建伪成功记录。
- 视频可进入现有剪辑工作台；图片和音频本期只做素材管理、分析、预览和上传，不扩展当前渲染协议。

### 4.5 商户私有云端上传

- 默认仅本机保存，用户可单个或批量主动上传商户私有云端副本。
- 上传成功后保留本机副本。
- 9000 生成商户受控存储键，真实流式写入临时文件，校验大小与 SHA-256 后原子提交。
- 上传失败保持原本机文件和先前可用云端对象不变，不得显示“云端可用”。
- 云端对象不得转为平台素材，也不得跨商户复用存储键。
- 若文件原子提交后数据库事务失败，只把本次新建对象的精确存储键、SHA-256 和创建时间写入受控孤儿清单；清理器不得扫描目录，只能处理清单中位于可信商户前缀内的条目，并须等待至少 24 小时、确认无任何 metadata 引用且 SHA-256 仍匹配后才删除。该清单仅用于防止误删既有对象，不形成用户功能。

## 5. 架构与职责

### 5.1 React

- 从 9000 读取权威素材、分析和云端状态。
- 本机文件操作调用浏览器所在电脑的 `127.0.0.1:19000`。
- 不持有 9100 internal token，不自报商户 ID，不中转整段云端媒体。

### 5.2 19000

- 作为原始本机素材文件真源和本机执行协调者。
- 导入时使用随机临时名流式写文件、计算 SHA-256、探测真实媒体；客户端文件名只作脱敏展示名，禁止参与受管路径拼接。
- 导入采用两阶段提交：先调用 9000 只读 `resolve` 取得规范 ID，再把文件原子落到规范路径并写本地 `pending_finalize` 清单，最后调用 9000 `finalize` 创建或恢复权威记录；finalize 成功后本地清单才切为 active。
- `resolve` 后本机落盘失败不得修改 9000；finalize 失败或响应丢失时，本地 pending 文件不对用户可见，19000 重启后按规范 ID 和 SHA-256 幂等重放 finalize，超期且从未 finalize 的 pending 文件才可清理。
- 执行本地分析、增稳和上传，持久化 attempt 与待回写状态。
- 轮询 9000 已领取的到期清理操作，按 operation ID 幂等删除本地副本并回执。
- 每个安装实例使用稳定 `agent_client_id`，生成后持久化在 PyInstaller 临时目录之外；首次鉴权心跳把 token 指纹与该 ID 绑定进 9000 Local Agent 鉴权上下文，后续不接受请求体覆盖或不同 ID 冒用。Task 12 保持“一份素材一个活动本机所有者”，其他设备补副本属于后续范围。

### 5.3 9000

- 作为素材归属、生命周期、分阶段状态、人工确认和云端对象 metadata 真源。
- 从登录态或 Local Agent token 映射取得可信商户，不接受前端商户参数。
- 后台定时领取到期删除，并在收到 19000 本地清理回执后幂等清理云端对象、完成操作。
- 代理调用 9100，不向公共响应泄露商户 ID、路径、存储键或令牌。

### 5.4 9100

- 只接受 9000 内部鉴权请求。
- 只接收媒体摘要、时间区间、压缩关键帧和必要转写片段，不接收本机路径或原始视频。
- 返回严格结构化描述、分类、标签、高光、可用区间和置信度。
- 失败只影响内容分析阶段，不生成规则兜底假结果。

## 6. 数据合同

### 6.1 保留字段与兼容退役

以下字段继续保留在 ORM、SQLite 和 PostgreSQL 内部模型中：

- `scope`
- `deleted_at`
- `purge_after`
- `purge_operation_id`
- `purge_status`

`scope` 仍允许历史值 `merchant/platform`，但新写入只允许 `scope=merchant` 且 `merchant_id` 非空。历史 `scope=platform` 行原样保留，不做数据迁移、合并或删除。

迁移策略固定为：当前尚未通过检查点 A 的 SQLite `0034` / PostgreSQL `0015` 继续吸收已验证的结构守卫硬化，保证新库升级不会假成功；新增 `analysis_attempt_count` 使用后继 SQLite `0035` 与 PostgreSQL `0016`，保证已经停在 0034/0015 的开发库也能正常前进。不得删除或改写 migration head 记录绕过升级。

### 6.2 生命周期状态

```text
active
  -> deleted_waiting：deleted_at/purge_after 非空，purge_status 为空
  -> preparing：purge_operation_id 非空，purge_status=preparing
  -> completed：原 operation ID 保留，purge_status=completed
```

- `preparing` 期间禁止重导恢复、新任务引用和第二次清理领取。
- `completed` 是保留业务 ID 和追溯关系的 tombstone，不代表可以从公共 API 查询。
- 任一状态变更必须在单事务内满足现有 purge 配对约束。

### 6.3 到期清理协议

1. 9000 只扫描 `scope='merchant' AND merchant_id IS NOT NULL AND deleted_at IS NOT NULL AND purge_after <= now AND purge_status IS NULL`；历史平台行永不进入清理候选。
2. 9000 在同一事务内确认无活动任务引用，再以条件更新领取一条记录，写入随机 `purge_operation_id` 和 `preparing`；任务创建同时拒绝已删除或正在清理的素材。
3. 19000 只轮询 token 映射商户且 `agent_client_id` 与当前鉴权设备一致的 claim，校验 operation ID 后幂等删除本地受管副本；只有匹配设备的本地清单确认该素材已删除或不存在时，文件不存在才可作为重放成功。
4. 19000 回执 operation ID。9000 复核当前 claim 后幂等删除商户云端对象和缩略图。
5. 只有本地回执成功且云端对象、缩略图删除成功或确认从未存在时，9000 才原子清空 `cloud_storage_key/thumbnail_storage_key`、设置 `storage_mode=local_missing` 并写 `completed`；历史分析和任务引用保留。
6. 19000 离线、回执丢失、云端失败或数据库失败时保持 `preparing`；单轮重试次数和退避时间有上限，下一轮调度继续处理，不伪造完成。

`restored` 必须在单事务清空 `deleted_at/purge_after`；`recreated` 必须在校验当前 completed operation 后，同事务清空 `deleted_at/purge_after/purge_operation_id/purge_status` 并重置存储与阶段状态。旧 operation 的后续回执只能得到中性冲突，不能删除已恢复内容。

清理全过程禁止输出绝对路径、存储键和令牌。日志只保留素材 ID、operation ID 指纹、阶段、目标类型、结果和 `failure_stage`。

### 6.4 分阶段状态与分析快照

- `ai_edit_material_processes` 延续五阶段：`media_probe/transcript/content_analysis/stability/cloud_upload`。
- 回写必须匹配 token 映射的可信 `merchant_id + material_id + source_sha256 + stage + attempt_count + execution_token_hash`，不能只按全局 material ID 查询。
- 19000 在请求 claim 前生成并持久化原始执行令牌，只把 SHA-256 摘要和 `expected_attempt` 发给 9000；9000 永不返回或保存原始令牌。若响应丢失，19000 以相同 expected attempt 和摘要重放，9000 在当前 attempt 已推进且摘要相同时幂等返回同一 attempt，摘要不同才返回 409。
- `ai_edit_material_analyses` 增加 `analysis_attempt_count` 并保存不可变版本快照；查询只合并当前源哈希、当前 `content_analysis` attempt 且该阶段 succeeded 的最新快照和人工覆盖。`recreated` 推进 attempt 后，旧快照继续保留但不再作为当前结果返回。

### 6.5 并发串行化

- 任务创建、删除、重导 finalize、阶段 claim、云端上传提交和清理领取必须经过同一素材变更 helper。
- PostgreSQL 对涉及的素材行按 `material_id` 排序后 `SELECT FOR UPDATE`；SQLite 使用现有迁移/测试允许的写事务串行化，并以相同条件更新模拟 CAS，不扩散到业务层。
- 清理领取条件必须包含 `purge_status IS NULL`；恢复条件必须包含预期 deleted/completed 状态；任一条件更新影响行数不是 1 时返回稳定 409。
- 任务创建在锁内复核 `scope=merchant`、可信商户、`deleted_at IS NULL`、`purge_status IS NULL`；删除在同一锁内复核活动引用。
- 必测竞争：两个清理领取者只有一个成功；恢复与清理领取只有一个成功；任务创建与删除只有一个成功。固定锁顺序防止多素材任务死锁。

## 7. API 合同

### 7.1 9000 用户接口

`GET /ai-edit/materials` 固定过滤：

```text
scope = merchant
merchant_id = RequestContext.merchant_id
deleted_at IS NULL
```

接口不接受 `scope` 或 `lifecycle` 参数。允许关键词、分类、标签、阶段状态、时长、创建时间、排序和分页。

- `GET /ai-edit/materials/{material_id}`：只返回当前商户活跃私有素材详情。
- `GET /ai-edit/materials/{material_id}/thumbnail`：登录态缩略图。
- `GET /ai-edit/materials/{material_id}/content`：当前商户云端分段预览。
- `PATCH /ai-edit/materials/{material_id}/annotations`：人工确认。

历史平台素材、跨商户素材和已删除素材统一返回 `404 MATERIAL_NOT_FOUND`，不得泄露真实归属或生命周期。

新前端删除唯一入口固定为“浏览器 -> 19000 -> 9000 Agent 删除”。9000 现有用户直删路由 `DELETE /ai-edit/materials/{material_id}` 兼容退役为 `410 DIRECT_MATERIAL_DELETE_DISABLED`，不得继续执行 metadata 删除，避免绕过本地协调。

### 7.2 取消的接口

以下能力不得新增；旧计划中的对应红灯和占位路由由新执行包删除或替换：

- `/admin/ai-edit/materials` 全部平台管理路由。
- 平台发布路由。
- 用户回收站列表路由。
- 用户恢复路由。
- 用户立即永久删除路由。

上述取消路由不得注册，直接请求统一 404。只有 9000 用户直删兼容路由按 §7.1 固定返回 410。

### 7.3 9000 Local Agent 接口

继续使用 `X-Local-Agent-Token` 映射可信 `merchant_id + agent_client_id`，请求体不得出现可自报的商户或设备字段。

| 方法与路径 | 关键请求 | 成功响应 | 幂等/冲突语义 |
|---|---|---|---|
| `POST /ai-edit/materials/agent/resolve` | `media_type/source_sha256/file_size_bytes` | `material_id/disposition` | 只读；新记录 ID 固定为 `mat_ + sha256(merchant_id + ':' + source_sha256 + ':v1')[:40]`；preparing 返回 409 |
| `POST /ai-edit/materials/agent/finalize` | `material_id/source_sha256/media_type/file_size_bytes/display_name/media_profile` | 规范素材安全 DTO + disposition | 锁内重新判定状态；重复 finalize 返回同一结果；ID/SHA 不匹配返回 409 |
| `DELETE /ai-edit/materials/agent/{material_id}` | 无 | 首次 `deleted_at/purge_after` | 重复删除返回首次时间，不刷新窗口；活动引用返回 409 |
| `POST /ai-edit/materials/agent/{material_id}/processes/{stage}/claim` | `source_sha256/expected_attempt/execution_token_hash` | 当前已领取 attempt，不返回原始令牌 | 相同 expected attempt + 摘要可幂等重放；摘要不同或生命周期非 active 返回 409 |
| `PATCH /ai-edit/materials/agent/{material_id}/processes/{stage}` | `source_sha256/attempt/progress/status/failure`，令牌走专用请求头 | 安全阶段 DTO | 匹配可信商户、SHA、stage、attempt、令牌和活跃生命周期 |
| `POST /ai-edit/materials/agent/{material_id}/analyses` | 严格分析 DTO，无路径 | 新分析版本 | 只接受当前源 SHA 和有效 attempt |
| `PUT /ai-edit/materials/agent/{material_id}/content` | 流式字节 + `source_sha256/attempt`、期望大小/SHA 请求头，执行令牌走专用请求头 | `storage_mode=cloud_available` | 必须先 claim `cloud_upload`，锁内复核 active 生命周期、商户、设备、attempt 和令牌；临时文件复验后原子提交 |
| `GET /ai-edit/materials/agent/purge-claims` | 无 | 仅当前设备的待清理 operation | 不返回云端存储键或其他设备 claim |
| `POST /ai-edit/materials/agent/{material_id}/purge-ack` | `purge_operation_id/local_result` | 当前 purge 状态 | 错商户或错设备统一 `404 MATERIAL_NOT_FOUND`；同设备旧 operation 返回 `409 PURGE_OPERATION_STALE` |

所有写接口必须幂等并拒绝旧 attempt。`preparing` 重导固定返回 `409 MATERIAL_CLEANUP_IN_PROGRESS`。

### 7.4 19000 浏览器接口

| 方法与路径 | 用途 | 边界 |
|---|---|---|
| `GET /agent/ai-edit/materials` | 当前设备活跃素材摘要 | 不返回删除字段、绝对/相对路径或内部清理状态 |
| `POST /agent/ai-edit/materials/import-stream` | 批量中的单文件两阶段导入 | 原始流、随机临时名、逐项 disposition |
| `DELETE /agent/ai-edit/materials/{material_id}` | 用户删除唯一入口 | 按 §4.2 先提交 9000，再隐藏本地清单 |
| `POST /agent/ai-edit/materials/{material_id}/analyze` | 重新分析 | 领取新 attempt，不复用旧令牌 |
| `POST /agent/ai-edit/materials/{material_id}/stabilize` | 一键增稳 | 生成私有衍生素材，不覆盖原素材 |
| `POST /agent/ai-edit/materials/{material_id}/upload` | 主动上传商户云端 | 19000 读取受管文件并流式提交 9000 |
| `GET /agent/ai-edit/materials/{material_id}/preview` | 本机真实预览 | 必须带 Local Agent token 请求头；只读受管低分辨率预览代理，不在 URL 放票据或路径；代理未生成返回 `409 PREVIEW_NOT_READY` |

本机预览响应固定 `Cache-Control: no-store`，日志不得记录 Local Agent token。预览代理有可配置大小上限，前端通过带鉴权请求获取 Blob/Object URL，页面卸载时释放；执行包必须验证大文件峰值内存和首帧时间。取消的恢复、永久删除和平台路由不得在 19000 注册。

### 7.5 9100 内部接口

- 固定 `POST /internal/ai-edit/materials/analyze`，只接受 9000 internal token。
- 请求只含可信素材 ID、媒体参数、场景时间、必要转写片段和压缩关键帧；总请求不超过 8MB，最多 12 帧，单帧解码后不超过 512KB、最大边不超过 720px，只接受 JPEG/WEBP 魔数。
- 响应严格包含描述、分类、标签、高光、可用区间和置信度；所有区间必须在真实时长内。
- 请求/响应均禁止路径、存储键、浏览器商户参数、原始视频和模型原始自由文本。模型拒答、超时、结构错误只使 `content_analysis` 失败。

### 7.6 公共 DTO 与前端类型

`AiEditMaterialOut`、`AiEditMaterialDetailOut` 和 `frontend/src/features/ai-edit/types.ts` 移除：

- `scope`
- `deleted_at`
- `purge_after`

公共 DTO 继续禁止：`merchant_id`、绝对路径、相对受管路径、`storage_key`、`cloud_storage_key`、`thumbnail_storage_key`、`purge_operation_id`、`purge_status`、执行令牌与令牌摘要。

19000 面向浏览器的素材列表也只返回活跃记录，前端类型不保留删除字段。内部本地清单继续保存删除和清理信息。

## 8. 前端设计

### 8.1 冻结区域

以下区域不修改：

- 全局导航栏。
- `AI小高剪辑` 标题栏及当前颜色体系。
- `ModuleTabs` 的“素材库 / 剪辑工作台”切换与路径。
- 剪辑工作台既有页面。

### 8.2 私有素材单视图

- 删除“私有素材 / 平台公共 / 回收站”二级标签整行。
- 内容区只展示当前商户私有素材，不显示“范围”列或“公共/私有”徽标。
- 桌面端保留左侧分类/标签、中间网格或列表、右侧预览详情的工作区结构。
- 移动端使用单栏素材区，筛选进入抽屉，详情全屏打开。
- 色彩复用当前背景 `#f3f6fa`、边框 `#e4e8f0`、主文字和深色按钮 `#1a1f2e` 以及现有状态色。

### 8.3 操作

- 支持拖拽、多选文件和文件夹导入；单个失败不终止批次。
- 支持搜索、分类、标签、阶段状态、云端状态、时长、导入时间和排序。
- 支持批量分析、上传云端、分类/标签和删除。
- 详情提供真实预览、媒体参数、五阶段状态、时间轴、人工确认、重新分析、一键增稳、上传云端和“用于剪辑”。
- 只有视频可用于当前剪辑工作台；图片和音频入口禁用，9000 和 Worker 再次校验。
- 不显示恢复、永久删除、平台发布或平台素材入口。

导入逐项反馈固定为：

| disposition/错误 | 前端反馈 | 列表行为 |
|---|---|---|
| `created` | “导入成功” | 批次结束刷新并选中新素材 |
| `existing` | “素材已存在” | 批次结束刷新并定位既有素材 |
| `restored` | “素材已恢复” | 批次结束刷新并定位原素材 |
| `recreated` | “素材已重新导入，正在重新分析” | 刷新并显示待处理阶段；不显示已上传 |
| `MATERIAL_CLEANUP_IN_PROGRESS` | “素材正在清理，请稍后重试” | 保留该项失败，不退化为通用导入失败 |

批量导入保持逐项结果，整个批次只刷新一次列表；一个文件失败不终止其他文件。

批量删除只弹一次同语义确认，随后逐项执行；活动引用 409 不阻断其他素材。完成汇总固定为“成功 N 个，活动任务占用 M 个，其他失败 K 个”，成功项立即从列表移除，失败项保留并显示逐项原因。

## 9. 异常与恢复

- 导入必须使用临时文件、真实媒体校验、9000 规范 ID 和原子落盘；失败不留下可见半成品。
- 9000 注册失败时删除本次临时文件；既有规范文件不得被失败重试覆盖。
- 分析和上传 attempt 持久化；19000 重启恢复未完成任务，旧 attempt 不能覆盖新状态。
- 上传中断只删除本次临时对象，保留原素材和既有可用对象。
- 9100 异常不影响本地媒体参数与稳定性结果，不伪造标签或高光。
- 清理回执丢失可按相同 operation ID 重放；未知或旧 operation ID 返回中性冲突。
- 日志必须包含 `stage`、素材 ID、输入摘要、判断结果和 `failure_stage`，敏感信息脱敏。

## 10. 安全与商户隔离

- 19000 继续只监听 `127.0.0.1`，鉴权保持开启。
- 9000 用户接口只信任 `RequestContext.merchant_id`；Agent 接口只信任 token 映射商户。
- 本机和云端路径必须位于商户受管根，拒绝路径穿越、符号链接和重解析点。
- 上传与预览必须校验媒体 ID、商户、大小、SHA-256 和范围请求。
- 9100 只接受 9000 internal token，请求中无本机路径、原始视频或不必要的个人信息。
- 历史平台、跨商户和已删除素材统一 404。
- 模板保存和任务创建同时拒绝任何平台素材引用，防止绕过前端。

## 11. 实施任务与检查点

### Task 12-R0：规格重排

冻结本设计，归档旧执行包，撤销失效集成路线。用户书面批准本规格后才生成新执行包。

旧 Task 12-1 中断言平台列表、回收站列表、用户恢复或永久删除的红灯测试已被本设计替代；新执行包必须删除或重写这些合同，不能把旧红灯当作必须保留的回归。

### Task 12-2R：数据守卫重建与检查点 A

在新执行包冻结的主线基线上重建 0034/0015 精确迁移守卫，并用 0035/0016 增加分析 attempt 关联字段。允许复用 `b8d9bbd43d3d01c850541c586892b86bb1147fde` 的已验证思路，但新候选必须产生新哈希并重新独立测试。检查点 A 验证历史平台行无损、已在 0034/0015 的库可继续升级、全新库完整升级、降级/再升级和事务回滚。

### Task 12-3：9000 私有素材控制面

实现私有单视图、规范 ID 去重、公共 DTO 收口、阶段状态、分析快照、人工确认、统一 404 和平台/回收站路由退役合同。

### Task 12-4：19000 导入与自动分析

实现规范 ID 落盘、媒体探测、转写、场景、关键帧、稳定性、重启恢复和本机预览。

### Task 12-5：9100 多模态语义分析

实现严格内部接口、最小输入、失败隔离、提示词注入保护和算力上报。

### Task 12-6：商户私有云端存储

实现流式上传、原子提交、校验、预览、重试、孤儿对象审计和商户隔离。

### Task 12-7：内部 7 天清理

实现后台领取、19000 轮询回执、云端清理、离线补偿、重导状态机和活动引用保护。完成后进入检查点 B。

### Task 12-8：私有素材库前端

实现单视图桌面/移动布局、真实预览、时间轴、批量导入和批量操作，不修改冻结区域。

### Task 12-9：本地/模拟闭环与检查点 C

完成四组件端到端、零外网哨兵、合成媒体、迁移、权限、前端构建和浏览器截图验收。

### Task 12-10：单入口测试 EXE 重建

检查点 C 通过后重建单入口测试 EXE。验证 19000、分析 Worker、FFmpeg、离线模型、私有云端临时目录、内部到期清理和端口释放；不连接宝塔生产环境。

## 12. 验收标准

### 12.1 数据与迁移

- 历史商户、平台、删除和任务引用数据无损。
- 0034/0015 结构守卫与 0035/0016 后继迁移的升级、降级、再升级通过；漂移结构和脏值显式拒绝并整体回滚。
- `(merchant_id, source_sha256)` 并发去重有效。
- 平台历史行保留，且列表、详情、缩略图、媒体内容、任务创建、模板保存、Local Agent 接口和超管直接调用均不可达；到期扫描永不领取平台行。

### 12.2 生命周期

- 删除活动引用返回 409。
- 删除成功后所有用户入口立即不可见，内部 `purge_after` 精确为 7 天窗口。
- 删除覆盖 9000 失败、9000 成功后 19000 本地写失败、响应丢失和 19000 重启四个边界；均不刷新 7 天窗口，不恢复旧阶段令牌。
- 7 天内同 SHA 重导返回原 ID并自动恢复。
- `preparing` 重导返回 `409 MATERIAL_CLEANUP_IN_PROGRESS`。
- `completed` 后重导返回原 ID并自动重新分析，云端状态保持本地且等待用户主动上传，历史任务仍可追溯。
- 19000 离线或云端失败时不写 `completed`；恢复后相同 operation ID 可继续。
- 错商户、错设备、旧 operation 回执不能推进清理；两个领取者、恢复对领取、任务创建对删除竞争均只有一方成功。

### 12.3 API 与安全

- 用户列表只返回当前商户 `scope=merchant AND deleted_at IS NULL`。
- 平台、跨商户、已删除详情统一 404。
- 公共 DTO 和前端类型无 `scope/deleted_at/purge_after` 及内部字段。
- `/admin/ai-edit/materials`、平台发布、用户恢复和永久删除路由均未注册，直接请求返回 404；用户直删兼容路由固定返回 410。
- Agent 分析、上传、删除和清理回写均以 token 映射的 `merchant_id + agent_client_id` 为可信上下文；请求体伪造两者无效。
- 本机预览只接受鉴权请求头，不在 URL、响应或访问日志暴露 token、票据、路径或存储键。
- 浏览器不直连 9100，不持有 internal token，不自报商户 ID。
- 测试期真实外部网络、生产数据库、宝塔和付费模型调用数为 0。

### 12.4 前端

- 页面无平台公共和回收站标签，无范围列，无恢复/永久删除/平台发布入口。
- 全局导航、标题栏、`ModuleTabs` 和剪辑工作台无回归。
- 删除确认文案与本设计一致。
- 批量导入、分析、云端上传、删除和失败逐项反馈可用。
- 1280x800 与 375x667 无白屏、横向溢出、遮挡或控制台错误。

## 13. 剩余风险

- 真正的 PostgreSQL 实例执行仍需批准的测试环境；本阶段默认只做静态合同与本地数据库测试。
- 真实宝塔目录、生产网络、真实付费多模态模型和客户生产素材统一留 Phase 13 后的生产验证执行包。
- 当前 Task 11 EXE 不包含本设计的自动分析、私有云端上传和内部到期清理闭环，不能作为 Task 12 完成证据。

## 14. 当前裁决

- 当前状态：`SPEC_REVIEW_PENDING`。
- `b8d9bbd43d3d01c850541c586892b86bb1147fde` 仅作为已独立验证的数据守卫参考，不是当前主线候选。
- `0d0aef1cf236580154a8684c37a9baabe9572628` 已失效，禁止使用。
- 新执行包尚未生成；本规格获用户书面批准前，执行窗口继续待命，测试窗口不得接收候选。
- 不得进入 Task 12-3，不得提前实现自动分析、云端上传、内部清理或新素材库界面。
