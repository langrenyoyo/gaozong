# 项目语言规范

请严格遵守以下规则：
1. 所有对话、解释、建议必须使用**简体中文**。
2. 代码注释必须使用中文。
3. 生成的 Commit Message 必须使用中文。
4. 严禁出现大段未翻译的英文技术名词。

# Ponytail, lazy senior dev mode



You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.

Before writing any code, stop at the first rung that holds:

1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the helper, util, or pattern that's already here, don't re-write it.
3. Does the standard library already do this? Use it.
4. Does a native platform feature cover it? Use it.
5. Does an already-installed dependency solve it? Use it.
6. Can this be one line? Make it one line.
7. Only then: write the minimum code that works.

The ladder runs after you understand the problem, not instead of it: read the task and the code it touches, trace the real flow end to end, then climb.

Bug fix = root cause, not symptom: a report names a symptom. Grep every caller of the function you touch and fix the shared function once — one guard there is a smaller diff than one per caller, and patching only the path the ticket names leaves a sibling caller still broken.

Rules:

- No abstractions that weren't explicitly requested.
- No new dependency if it can be avoided.
- No boilerplate nobody asked for.
- Deletion over addition. Boring over clever. Fewest files possible.
- Shortest working diff wins, but only once you understand the problem. The smallest change in the wrong place isn't lazy, it's a second bug.
- Question complex requests: "Do you actually need X, or does Y cover it?"
- Pick the edge-case-correct option when two stdlib approaches are the same size, lazy means less code, not the flimsier algorithm.
- Mark intentional simplifications with a comment. If the shortcut has a known ceiling (global lock, O(n²) scan, naive heuristic), the comment names the ceiling and the upgrade path.`ponytail:`

Not lazy about: understanding the problem (read it fully and trace the real flow before picking a rung, a small diff you don't understand is just laziness dressed up as efficiency), input validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs (the platform is never the spec ideal, a clock drifts, a sensor reads off), anything explicitly requested. Lazy code without its check is unfinished: non-trivial logic leaves ONE runnable check behind, the smallest thing that fails if the logic breaks (an assert-based demo/self-check or one small test file; no frameworks, no fixtures). Trivial one-liners need no test.

(Yes, this file also applies to agents working on the ponytail repo itself. Especially to them.)

# Project AI Entry Protocol

CLAUDE.md 是所有 VibeCoding / Codex / Claude Code 任务的项目入口文件。

开始任何任务前，必须第一步阅读 CLAUDE.md；随后再按 Required Reading Order 阅读 docs/ai 规则文件。

当前涉及 PostgreSQL、RAG、Milvus、NewCar 鉴权或知识训练任务时，必须额外阅读：

```text
AGENTS.md
docs/ai/05_PROJECT_CONTEXT.md
docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md
```

不得跳过 CLAUDE.md 直接进入代码、测试、日志或业务实现。

你正在参与一个真实项目开发。

本项目遵循分层 AI 协作规范。

开始任何任务前必须先阅读项目规范。

------

# Current Architecture Notes（2026-07）

1. PostgreSQL 目标方案已确认：方案 A，一个 PostgreSQL 实例，两个 database。
   - `auto_wechat`：9000 主服务数据库，未来使用 `DATABASE_URL`。
   - `xg_douyin_ai_cs`：9100 RAG / AI 客服 metadata 数据库，未来使用 `RAG_DATABASE_URL`。
2. SQLite 只是开发和过渡数据库；不要基于旧 SQLite-only 假设修改 RAG、训练、反馈或迁移逻辑。
3. Milvus 继续作为向量检索库，只是 embedding + 检索副本，不是 metadata 真源。documents、chunks、feedback、training_run 和状态字段的真源是 SQLite / PostgreSQL metadata。
4. Milvus 模式下，`ask` 不能因为 SQLite active count 为 0 跳过 RAG；`search-preview` 能命中 Milvus 时，`ask` 也必须执行 Milvus RAG。
5. 统一小高知识库训练和检索 scope 固定为 `tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=0`、`category_key=base`。
6. NewCar 真实鉴权本地联调必须显式设置 `NEWCAR_AUTH_ENABLED=true`、`NEWCAR_AUTH_MOCK_ENABLED=false`。
7. 退出登录必须走 `POST /auth/logout`，由 9000 调用 NewCarProject `POST /api/external-auth/logout`，不能只清本地 token。
8. 前端不得持有 internal token，不得直连 9100 / Milvus；不得触发抖音发送、私信发送或自动回复真实发送 gate。

------

# Rule Priority

CLAUDE.md 是入口规则和项目级约束汇总文件。

docs/ai 根目录保留入口规则与项目上下文；专题文档已按阶段和业务域归档到 docs/ai 子目录。

完整索引见：`docs/ai/README.md`。

优先级如下：

P-1 CLAUDE.md Entry Protocol
P0 Reading Rules
P1 Project Context
P2 Execution Rules
P3 Testing Rules
P4 Output Rules

发生冲突时：

CLAUDE.md Entry Protocol
>
Reading Rules
>
Project Context
>
Execution Rules
>
Testing Rules
>
Output Rules

------

# Current Project Status

项目名称：主机微信线索分发与销售跟进检测系统

当前阶段（2026-06-18 同步）：
- 微信助手主线：P1-END-1 自动检测单次闭环演示版已冻结验收（见 docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md）
- 抖音AI客服线：抖音AI小高客服（9100）多账号工作台已正式化（含真实私信会话接入、应用内抖音账号授权、抖音 OpenAPI 授权签名修复），前端 DouyinAiCsWorkbenchPage 已上线
- 文档体系：PRD（06）/架构（07）/数据模型（08）/接口契约（09）/Webhook 验签迁移（10）/代码计划（11）/测试计划（12）/DB 迁移（14）已落盘

最新冻结 PRD：`docs/ai/01_product_prd/06_PRD_AUTO_WECHAT.md`

当前产品定位：auto_wechat / 小高AI微信助手属于 NewCarProject 外部客户系统下的一组商户可售卖子功能系统。当前重点建设链路有两条：
- `AI小高线索 → 小高AI微信助手`（线索分发与销售跟进检测）
- `抖音AI小高客服（9100）`（私信客服工作台 + RAG/LLM 回复建议）

关键边界：
- NewCarProject 负责商户、账号、权限、菜单、套餐、消耗管理
- AI小高线索负责抖音扫码鉴权、抖音私信、原始线索事件、联系方式提取、有效线索生成
- 小高AI微信助手负责线索分配、微信通知任务、Local Agent、本地微信通知销售、回复检测、超时重分配、失败记录、人工处理、Excel 导出
- AI小高剪辑是独立售卖子功能系统，巨量一键过审属于 AI小高剪辑，不属于小高AI微信助手
- 小高算力不是子功能系统，是商户查看套餐和消耗的展示能力
- douyinAPI 当前定位为 demo / 参考实现 / 历史代码沉淀，不应作为长期正式生产依赖
- 第一版不接入 LLM，不保存截图，不把三个子功能混成一个服务

已完成：
- P0 项目初始化、数据库设计
- P1 线索入库、销售分配、回复检测
- P2 微信 UI 自动化检测
- P2.5 发送方识别实验（结论：保留兜底模式，截图/OCR 作为后续预研方向）
- P3 反馈发送（主机微信 B → 数据源 A）
- P4 douyinAPI 线索同步与自动分配
- P5 React UI Integration（线索列表、详情、同步、分配、检测记录、微信状态检测、局域网访问）
- P6 微信回复检测闭环（窗口识别、消息读取、关键词命中、自动检测调度器）
- P7 销售派单 Demo（联系人搜索、自动通知、自触发误判修复、紧急停止机制）
- P8 Demo 稳定化主要功能（小高AI微信助手配置、测试线索生成器、微信固定左侧、Alt+Q 紧急停止、桌面浮层、自动同步派单）
- P0-1 局域网访问修复
- P0-2 微信自动化稳定化（前台焦点守卫、白屏/灰屏诊断、Esc 隐藏修复、联系人确认策略、剪贴板修复）
- P0-3 本机微信自动化稳定性与安全门禁（前台焦点守卫、hidden/minimized 禁止恢复、剪贴板修复、OCR 识别验证、Aw3 debug 单发）
- P0-REPLY-2 Local Agent 销售回复检测 + 主系统回写（agent-write-back、sender 截图识别、UTF-8 修复）
- P0-REPLY-3B 截图像素分析识别微信消息 sender（self/friend/system），真机 Aw3 验证零误判
- P0-END-1 MVP 主链路冻结验收
- P1-AUTO-1A/B detect_reply task + 检测结果回写（detected_status / detect_count）
- P1-AUTO-1AB-FIX2 notify_sales pasted 后自动创建 detect_reply task + ReplyCheck 绑定
- P1-AUTO-1C 19000 poll-and-detect 端点 + read_only 只读检测
- P1-AUTO-1C-UTF8 19000 charset=utf-8 修复
- P1-AUTO-1D React 自动回复检测面板 + poll-and-execute/poll-and-detect task_id 指定执行
- P1-AUTO-1D-FIX2 poll-and-execute 支持 task_id
- P1-AUTO-1D-FIX3 poll-and-detect 支持 task_id，避免旧 pending 队列阻塞
- P1-AUTO-1D-FIX4 search-debug 安全序列化防止 500 RecursionError
- P0-DOC-PRD-1 PRD/架构/数据模型/接口契约/Webhook 验签迁移/代码计划/测试计划 文档体系（06~12）落盘
- DB-MIG + P2-A 数据库迁移骨架（migrations/migrate_sqlite.py + versions/0001_prd_base_fields.sql，13 迁移测试 + 748 全量回归通过，未改 models.py、未碰主线库）
- P0-DEV-A1 Webhook 生产验签安全改造（APP_ENV 环境识别，production 强制验签）
- P0-DEV-E1 原始事件 / invalid 只读查询接口（GET /webhook-events）
- 9100 抖音AI小高客服 RAG/LLM MVP（独立服务 apps/xg_douyin_ai_cs，SQLite RAG + OpenRouter chat）
- 9100 抖音AI客服多账号工作台正式化（DouyinAiCsWorkbenchPage：真实私信会话、应用内抖音账号授权、账号 Agent 绑定、抖音 OpenAPI 授权签名修复）
- React 前端并入 auto_wechat/frontend（提交 2c85433），不再独立位于 E:\work\project\react
- 本地 Docker 开发环境（docker-compose.dev.yml：9000 + 9100 + frontend，19000 不容器化）

当前版本定位（按子系统区分）：
- 微信助手（9000 + 19000）：✅ 自动检测单次闭环演示版；❌ 非后台无限轮询版；❌ 非自动发送版（业务派单 sent 仍为 false）
- 抖音AI客服（9100）：✅ 多账号工作台 + RAG/LLM 回复建议；❌ AI 回复 auto_send 恒为 false，不自动发送私信（reply_decision_service 全路径 auto_send=False）
- 全局：❌ 非多客户生产版（NewCarProject 对接字段、生产验签切换、状态机重构待落地）

进行中：
- P0-DOC-PRD-1 文档冻结与上下文同步
- P0-ARCH-1 架构设计与 Webhook 验签迁移说明（文档已同步，见 `docs/ai/02_architecture/07_ARCHITECTURE_AUTO_WECHAT.md`）
- P0-DATA-1 数据模型设计文档（文档已同步，见 `docs/ai/03_data_and_migration/08_DATA_MODEL_AUTO_WECHAT.md`）

下一步聚焦：
- 基于 `docs/ai/01_product_prd/06_PRD_AUTO_WECHAT.md` 拆分后续架构设计、数据模型设计、接口契约、测试验收计划
- 基于 `docs/ai/02_architecture/07_ARCHITECTURE_AUTO_WECHAT.md` 继续输出数据模型设计、接口契约和 Webhook 验签迁移技术方案
- 基于 `docs/ai/03_data_and_migration/08_DATA_MODEL_AUTO_WECHAT.md` 继续输出接口契约、Webhook 验签迁移技术方案和代码修改计划
- P1-END-2 修复前端 pasted 展示字段
- P1-END-3 清理/归档旧 pending 任务策略
- 历史自动检测计划项：后台定时轮询检测（旧编号 P2-A，后续按新的阶段总控重新排期）
- 历史自动检测计划项：客户配置化关键词/工作时间/销售（旧编号 P2-B，后续按新的阶段总控重新排期）

业务架构（2026-06-18 更新）：

```text
【微信助手线索链路】
抖音平台 / GMP 私信
    ↓ Webhook（callback.misanduo.com → 宝塔整站反代 → 9000）
auto_wechat（端口 9000，AI小高线索 + 小高AI微信助手）
    ↓ webhook 直收入库（im_receive_msg → 联系方式提取 → douyin_leads）
    ↓ 分配销售 → 创建微信任务
    ↓ UI Automation（经 Local Agent）
主机微信 B → 销售微信 C → 回复检测 → 9000 回写

【抖音AI客服链路（独立）】
抖音私信会话
    ↓ 9100 工作台拉取 / webhook 兜底生成账号
抖音AI小高客服（端口 9100，apps/xg_douyin_ai_cs）
    ↓ RAG 检索 + LLM 回复建议（auto_send=false，人工确认）
工作台前端（DouyinAiCsWorkbenchPage）
```

注：douyinAPI（8081）现为 demo / 参考实现 / 历史沉淀，webhook 事件回调已由 auto_wechat 9000 直收（见 05 文档第 28 章）；旧同步链路 `/integrations/douyin/sync-leads` 仍保留但非事件回调归属。

本地 Agent 架构（P0-4 新增）：

```text
开发主机（192.168.110.113）
  提供 React 页面（端口 5173）
  提供源码开发、打包

测试电脑 / 虚拟机（无源码）
  运行 小高AI微信助手.exe（监听 127.0.0.1:19000）
  浏览器访问 React → 点击按钮 → 调用本机 127.0.0.1:19000
  操作本机微信
```

关键约束：
- 微信自动化必须运行在微信所在的那台 Windows 电脑上
- 谁打开 React 页面，谁点击按钮，127.0.0.1 就是谁的电脑
- 虚拟机/测试电脑默认无源码，不得要求运行 python 命令作为验收
- React 的本机 Agent 测试按钮必须调用浏览器所在电脑的 127.0.0.1:19000，不走 VITE_API_BASE_URL
- 业务自动派单发送仍禁止

前端架构：

```text
React UI（端口 5173）
    ↓ axios API
auto_wechat（端口 9000）
    ↓ HTTP API
douyinAPI 测试环境（端口 8081）

React 本机 Agent 面板
    ↓ 直接调用
浏览器所在电脑 127.0.0.1:19000（小高AI微信助手.exe）
```

auto_wechat 的职责：

1. 获取 AI小高线索提供的有效线索
2. 分配销售
3. 创建微信通知任务
4. 调用 Local Agent 操作客户本地微信
5. 通知销售
6. 检测销售是否回复
7. 判断已回复 / 超时未回复
8. 支持超时重分配
9. 支持失败记录
10. 支持人工处理
11. 支持 Excel 数据导出

auto_wechat 不负责：

- 管理 NewCarProject 商户、账号、套餐、消耗、菜单
- 管理所有子功能权限
- AI小高线索的完整抖音扫码鉴权与私信线索能力
- AI小高剪辑 / 巨量一键过审
- 把 douyinAPI 作为长期正式生产依赖
- 第一版 LLM 判断
- 第一版截图保存或截图入库

技术约束：

```text
禁止使用：
  - 微信数据库解密
  - DLL 注入
  - 微信协议逆向

优先使用：
  - UI Automation
  - 视觉识别
  - OCR
```

------

# Upstream System Constraints

auto_wechat 不是线索源系统。

线索来源于上游系统 douyinAPI。

## 对接原则

优先通过 HTTP API 对接上游系统。

禁止：

- 数据库直读
- SQLite 文件共享
- 手工复制数据库

第一原则：系统之间通过 API 通信。

## 上游接口（douyinAPI）

拉取线索：

```text
GET http://douyinapi-host:8081/leads?lead_status=pending&page_size=50
GET http://douyinapi-host:8081/leads/export
```

字段映射（douyinAPI → auto_wechat）：

| douyinAPI 字段 | auto_wechat 字段 | 说明 |
|----------------|-----------------|------|
| open_id | source_id | 抖音用户唯一标识 |
| display_name | customer_name | 客户昵称 |
| last_interaction_record | content | 最近交互内容 |
| "douyin" | source | 来源平台 |
| "私信" | lead_type | 线索类型 |

## 本地开发原则

任何开发和测试：

不得修改生产 douyinAPI 数据。

必须支持：

- 本地 Mock 数据
- dry_run
- 本地 SQLite 测试库

禁止：

开发阶段直接连接生产数据库。

------

# System Architecture (2026-06)

当前系统由三个独立项目组成，各有明确职责边界：

```text
抖音平台
    ↓ Webhook
douyinAPI（上游数据源，端口 8081）
    ↓ HTTP API
auto_wechat（中间业务执行层，端口 9000）
    ↓ UI Automation
主机微信 B
    ↓ 微信消息
销售微信 C
    ↓ 回复检测
主机微信 B → 反馈给 douyinAPI
    ↓
React UI（客户运营后台，端口 5173）
```

## douyinAPI

路径：`E:\work\project\douyinAPI`

负责：

- 抖音 Webhook 接收
- 抖音私信会话管理
- 线索沉淀与存储
- 抖音授权管理

不负责：

- 销售分配
- 微信自动化
- 回复检测
- 主机微信反馈

## auto_wechat

路径：`E:\work\project\auto_wechat`

负责：

- 上游线索同步（从 douyinAPI 拉取）
- 销售分配
- 回复检测
- 超时检测
- 主机微信反馈
- 微信 UI 自动化

## 前端（已并入 auto_wechat/frontend）

路径：`E:\work\project\auto_wechat\frontend`（原独立项目 `E:\work\project\react` 已并入，提交 2c85433）

负责：

- 客户运营后台展示
- 线索管理 / 销售管理 / 检测记录 / 报表
- 微信助手（WechatAgent）/ 本机 Agent 测试面板
- 抖音AI小高客服工作台（DouyinAiCsWorkbenchPage）+ 测试面板（DouyinAiCsTestPage）
- 抖音直播间检测（DouyinLiveCheckPage）
- 超管后台系列（商户管理、账号、AI 回复记录、算力配置、跟进话术、禁用词、商户 Agent 绑定）
- webhook 事件查看（WebhookEventsPage）

当前状态（2026-06-18 更新）：

- 多页面已接入真实 API（线索、销售、检测、报表、微信助手、抖音客服工作台、webhook 事件、超管后台）
- API 层已扩展至 17 个模块（client/types/leads/staff/reports/integrations/checks/replies/notifications/wechat/wechatTasks/wechatAutoDetect/automation/agent/localWechatAgent/webhookEvents/douyinAiCsClient/douyinLiveCheck）
- 环境变量示例：`frontend/.env.example`（VITE_API_BASE_URL / VITE_AUTO_WECHAT_API_BASE_URL=9000 / VITE_LOCAL_WECHAT_AGENT_BASE_URL=19000 / VITE_DOUYIN_AI_CS_API_BASE_URL=9100）
- TS 配置约束：ignoreDeprecations=5.0 / composite / emitDeclarationOnly（详见下文 React TypeScript 配置约束）

------

# Development Strategy

当前阶段：P8 Demo Hardening / P0 Risk Fixes

目标：让连续演示稳定可靠，修复产品化验证风险

原则：

1. HTTP API 对接
2. 不共享数据库
3. 不直读 SQLite
4. 不修改 douyinAPI
5. 本地测试优先
6. Demo 优先验证，生产化后置
7. 不新增业务功能，专注稳定化

## 已完成阶段

- P4：douyinAPI Integration（线索同步、入库、自动/手动分配）
- P5：React UI Integration（线索列表、详情、同步、分配、检测记录、微信状态检测、局域网访问）
- P6：WeChat Reply Detection（窗口识别、消息读取、关键词命中、自动检测调度器）
- P7：Sales Dispatch Demo（联系人搜索、自动通知、自触发误判修复、紧急停止机制）

## P8 实施路线

- P8-1：WechatAgent 添加销售配置接入 POST /staff（已完成 ✅）
- P8-2：douyinAPI 开发测试线索自动生成器（已完成 ✅）
- P8-3：React 自动同步派单 + 后端 auto_notify（已完成 ✅）
- P8-4：Alt+Q 全局紧急停止 + 桌面提示浮层（已完成 ✅）
- P8-5：微信固定左侧布局（已完成 ✅）

## P0 风险修复

- P0-1：局域网访问修复（已完成 ✅）
- P0-2：微信自动化稳定化（已完成 ✅：前台焦点守卫、白屏/灰屏诊断、Esc 隐藏修复、联系人确认策略）
- P0-3：本机微信自动化稳定性与安全门禁（已完成 ✅：OCR 验证、Aw3 debug 单发）
- P0-4：本地 Agent / exe 架构验证（进行中）
  - P0-4A：初版 local agent + exe（已完成 ✅）
  - P0-4A-1：微信窗口发现诊断（已完成 ✅）
  - P0-4A-2：前台焦点交接诊断（已完成 ✅）
  - P0-4A-3：/agent/wechat/test 自动打开 Aw3 → OCR → paste_only（下一步）
- P0-5：多目标检测队列（待做）

------

# Frontend Strategy

重要结论：

React 项目（`E:\work\project\react`）是最终交付界面。

不要新建第二套前端。

开发方式：

React 页面逐步替换 Mock 数据，接入 auto_wechat 和 douyinAPI 真实接口。

当前进展：

LeadsManagement 页面已完成真实 API 接入，不再使用 Mock 数据。

API 层架构：

```text
src/api/client.ts        — axios 实例（baseURL 从环境变量读取）
src/api/types.ts         — TypeScript 类型定义（与 auto_wechat schemas 对齐）
src/api/leads.ts         — 线索 API（GET /leads, GET /leads/{id}）
src/api/staff.ts         — 销售 API（GET /staff）
src/api/reports.ts       — 报表 API（GET /reports/summary）
src/api/integrations.ts  — 同步 API（POST /integrations/douyin/sync-leads）
```

------

# P7 Sales Dispatch Demo（已完成 ✅）

P7 已完成"通知销售"环节。

完整业务链路：

```text
douyinAPI → auto_wechat sync → assign staff
    → open sales WeChat chat by nickname
    → send lead notification
    → sales replies
    → auto detect reply
    → mark lead as replied
    → React shows 已跟进
```

P7 已完成：

- P7-0：探索小猫AI员工与 ai-bot-pc（结论：继续使用 uiautomation + input_writer）
- P7-1：微信联系人搜索（contact_searcher.py）
- P7-2：线索通知发送（notification_service + lead_notifications 记录）
- P7-3：发送后设置自动检测目标
- P7-4：销售回复后自动检测并更新已跟进
- P7-BUG-1：自触发误判修复（通知模板去关键词、静默期、exclude_text_list）
- P7-STOP-1：紧急停止机制（/automation/status、/emergency-stop、/resume、6 个自动化入口 guard、前端停止按钮）

## P7 安全边界

- 禁止读取微信数据库
- 禁止使用微信协议
- 禁止 DLL 注入
- Demo 可使用 UI 自动化
- 自动搜索联系人存在误发风险
- 如果自动搜索失败，必须降级为"用户手动打开销售窗口 → 系统发送当前窗口"
- auto_send 只用于 Demo 验证，后续生产应默认 require_confirm=true
- 所有发送动作必须记录 lead_notifications 或等效日志

------

# P8 Demo Hardening（主要功能已完成 ✅）

P8 目标不是新增业务功能，而是让连续演示稳定可靠。

P8 完整业务链路：

```text
douyinAPI 自动生成测试线索
    → React 自动同步派单
    → auto_wechat 同步入库
    → 自动分配销售
    → 自动搜索销售微信昵称
    → 自动发送线索通知
    → 自动设置检测目标
    → 销售回复
    → 自动检测
    → lead.status=replied
    → React 显示已跟进
```

P8 已完成：

1. WechatAgent 添加销售配置接入 POST /staff
2. douyinAPI /dev/test-leads/start/stop/status
3. 微信窗口固定左侧布局
4. Alt+Q 全局紧急停止
5. 桌面自动化状态浮层
6. 自动同步派单 auto_notify
7. P7 自触发误判修复
8. 局域网访问修复

P8 真实验证结果：

- 线索同步：7/7 新建成功
- 自动分配：7/7
- 自动通知：7/7
- 联系人搜索：4/4 成功
- 用户确认收到微信通知
- 紧急停止机制生效
- 桌面浮层和 Alt+Q 已运行
- 自动检测存在单目标覆盖问题，检测成功率约 13/28（46%）

------

# P0-3 微信自动化稳定性与安全门禁（已完成 ✅）

P0-3 主要解决本机微信自动化稳定性和安全门禁。

P0-3 已完成：

1. **P0-3A Render Ready 诊断**：debug_wechat_render_state.py，发现前台焦点丢失、hidden 恢复导致灰屏等问题
2. **P0-3B 前台焦点守卫**：ensure_wechat_foreground，Ctrl+A/Backspace/Ctrl+V/Down/Enter 前检查微信是否前台，失败不继续
3. **P0-3C hidden/minimized 禁止恢复**：业务路径禁止从 hidden/minimized 微信自动恢复后继续执行，必须提示人工打开
4. **P0-3D 剪贴板修复**：统一剪贴板工具，pyperclip 优先 + Win32 fallback 修复 64 位句柄问题
5. **P0-3E 联系人确认真实验证**：open_chat_by_nickname 能打开聊天，但纯 UIA 无法可靠读取 Qt5 微信标题/资料卡
6. **P0-3F 截图链路修复**：修复 screenshot_debug.py Win32 64 位 GDI 句柄问题，100 次截图压力测试通过
7. **P0-3G OCR 最小实测**：EasyOCR 安装，Aw3 顶部标题 OCR 5/5 成功，啊东、只能识别主体
8. **P0-3H OCR 接入联系人验证**：ocr_matcher.py + contact_ocr_verifier.py，Aw3 5/5 verified，啊东、5/5 partial_match
9. **P0-3I Aw3 单条发送复测**：debug_aw3_single_send.py，paste-only 成功，single_send 成功，但业务自动派单发送仍未放开

P0-3 结论：
- Aw3 是当前唯一允许自动验证和 debug 测试的联系人（OCR 5/5 verified）
- 啊东、只能 partial_match，不允许自动发送
- P0-3I 证明 debug 单发链路可用，不代表业务自动发送已放开

------

# P0-4 本地 Agent / exe 架构验证（进行中）

P0-4 目标：验证测试电脑无源码运行小高AI微信助手.exe，由 React 页面调用测试电脑本机 127.0.0.1:19000 操作本机微信。

本地 Agent 命名：**小高AI微信助手**（exe：小高AI微信助手.exe）

P0-4 已完成：

1. **P0-4A 初版 local agent**：app/local_agent_main.py，监听 127.0.0.1:19000，GET /health + POST /agent/wechat/test
2. **P0-4A 修正版 exe**：app/local_agent_exe_entry.py + PyInstaller onedir 打包，开发机 /health smoke test 通过
3. **P0-4A-1 微信窗口发现诊断**：GET /agent/wechat/windows，find_wechat_window 增强 Win32 枚举，排除误识别
4. **P0-4A-2 前台焦点交接诊断**：POST /agent/wechat/foreground-debug，SetForegroundWindow + BringWindowToTop + AttachThreadInput + Alt wakeup

Windows 11 虚拟机真实状态：
- ✅ 能访问开发主机 React（http://192.168.110.113:5173）
- ✅ 能运行小高AI微信助手.exe
- ✅ React 检测虚拟机本机 Agent online=true（hostname: DESKTOP-TQHE53J）
- ✅ 诊断微信窗口成功
- ✅ 前台焦点诊断成功
- ❌ 点击「启动微信测试」后未自动切换到 Aw3（提示：联系人验证需要人工复核，禁止发送）
- ❌ 虚拟机 Aw3 输入框未出现测试消息

当前真实阻塞：
- /agent/wechat/test 只验证当前聊天窗口，没有自动执行 open_chat_by_nickname("Aw3")

P0-4 下一步：
- **P0-4A-3**：/agent/wechat/test 自动执行 readiness → foreground → open_chat_by_nickname("Aw3") → verify OCR → paste_only → sent=false
- P0-4B：安装包/分发优化
- P0-4C：Windows 10 测试电脑复测

------

# Current Safety Gates（当前活跃安全约束）

以下约束在 P0-4A-3 通过前必须严格执行：

1. **业务自动派单发送仍禁止**（sent 必须为 false）
2. P0-4A 只验证本地 Agent 架构和 Aw3 paste_only
3. Aw3 是唯一允许自动验证和 debug 测试的联系人
4. 啊东、只能 partial_match，不允许自动发送
5. partial_match 不允许 verified=true
6. manual_review_required=true 不允许粘贴或发送
7. hidden/minimized 微信不允许自动恢复后继续
8. ESC 不允许业务路径使用后继续
9. foreground guard 失败必须停止
10. OCR/截图失败不能伪造成功
11. 小高AI微信助手.exe 不应监听 0.0.0.0，默认只监听 127.0.0.1:19000
12. React 本机 Agent 面板不能使用 VITE_API_BASE_URL
13. 不能操作开发主机微信作为测试电脑结果

## WeChat Automation Safety Boundary

以下边界适用于当前所有微信自动化任务，除非用户明确批准，不得放宽：

1. 不允许绕过 foreground_guard。
2. 不允许绕过 search_focus guard。
3. 不允许绕过 search_text_verified。
4. 不允许未经验证直接粘贴。
5. 不允许发送 Ctrl+V。
6. 不允许发送 Enter。
7. 不允许把 sent 置为 true。
8. 不允许业务自动派单发送。

# LAN Access Rules

局域网演示必须使用：

auto_wechat：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

React：

```bash
npm run dev:lan
```

React LAN 环境变量：

```text
VITE_AUTO_WECHAT_API_BASE_URL=http://192.168.110.113:9000
```

不能使用：

```text
VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000
```

因为局域网其他机器访问 React 时，127.0.0.1 指向访问者自己的机器。

CORS 必须允许：

- `http://192.168.110.113:5173`
- `http://DESKTOP-T0HA3GO:5173`
- `http://localhost:5173`
- `http://127.0.0.1:5173`

防火墙规则：TCP 9000、TCP 5173

------

# Current Known Risks

## P0 — 必须修复

1. **服务器需重启加载最新代码**：9000 和 19000 当前运行的是 P0-4A-3 时代的旧代码，需手动重启加载 P0-REPLY-3B + UTF-8 修复。

2. **自动检测单目标覆盖**：wechat_active_check_id 只能保存一个 check。多条线索连续发送时后发覆盖前一个目标。P0-5 需要升级为多目标检测队列。

## P1 — 产品化优化

1. 桌面浮层需要改为更明显的常驻控制中心
2. 演示数据需要清理，避免无 wechat_nickname 的销售导致 failed
3. 自动同步派单耗时较长，当前是串行搜索+发送
4. 啊东、等中文昵称 OCR 识别不稳定，需要继续优化或采用人工确认兜底

## P2 — 架构验证

1. Windows 10 测试电脑尚未复测
2. 小高AI微信助手.exe 安装包/分发方案待设计

------

# Product Architecture Clarification

## 机器角色

| 角色 | IP | 说明 |
|------|-----|------|
| 开发主机 | 192.168.110.113 | 提供 React 页面、源码开发、打包。路径：auto_wechat、react |
| Windows 11 虚拟机 | — | 无源码、无 conda，只运行小高AI微信助手.exe。验证无源码闭环 |
| Windows 10 测试电脑 | — | 同样作为真实物理 Agent 测试机，后续复制同一份 exe 验证 |

核心架构原则：

- 微信自动化只能发生在运行小高AI微信助手.exe 的 Windows 电脑上
- React 页面按钮直连浏览器所在电脑的 127.0.0.1:19000
- 开发主机微信不会被测试电脑的操作影响
- 虚拟机/测试电脑默认没有项目代码，不能以"运行 Python 命令"作为验收前提

未来产品化方向：

```text
中心服务 / 管理后台
    → 多个 Windows Agent（小高AI微信助手.exe）
    → 每个 Agent 控制本机微信
```

## P7 参考软件探索结论（P7-0 已完成）

### 小猫AI员工

- PyInstaller + Cython .pyd
- wxauto 核心 .pyd 不可读
- 可读部分显示其发送机制本质是剪贴板 + Ctrl+V + Enter
- 消息读取使用 UIAutomation 消息列表解析
- 有任务调度数据库，但不是销售线索分配业务
- 当前微信版本存在 wxauto 不兼容问题
- 不建议直接复用 wxauto / DLL / wecom 注入方案
- 可参考任务调度、状态记录、UIAutomation 思路

### ai-bot-pc

- Electron 38 + Vue 3 + TypeScript
- 本地只是瘦客户端
- 业务逻辑在服务端
- 本地无微信自动化能力
- 无任务分发、无销售/线索概念、无本地数据库
- 对 P7 设计不产生改变

结论：auto_wechat 继续使用 uiautomation + input_writer 方案。

## 微信窗口布局策略

微信窗口默认应移动到左侧。

原因：React 右侧详情区域包含核心按钮（设为自动检测目标、检测微信回复、发送线索给销售），微信放右侧会遮挡操作按钮。

推荐工作台布局：

```text
微信窗口（左侧）  |  React 后台（右侧）
```

当前 activate_wechat_window 已支持窗口移动。后续默认应从右上角改为左侧布局。

Demo 可先默认 left。

------

# React TypeScript 配置约束

React 项目（`E:\work\project\react`）使用 TypeScript 5.9 + Vite 项目模板。

以下约束经 2026-06-09 确认为最终稳定配置，禁止后续开发修改。

### Constraint 1 — ignoreDeprecations

所有 TS 配置文件必须保留：

```json
{
  "ignoreDeprecations": "5.0"
}
```

**版本兼容说明（2026-06-09 验证）：**

- 项目 TypeScript 版本：5.9.3
- `"5.0"` 是当前 TS 5.9.3 支持的正确值，构建通过
- `"6.0"` 尚未被 TS 5.9.3 支持，会导致 `TS5103: Invalid value for '--ignoreDeprecations'` 构建失败
- VSCode 可能使用更高版本的 TypeScript 语言服务，提示使用 `"6.0"`，但项目构建器不支持
- 结论：保持 `"5.0"`，忽略 VSCode 中该提示；升级 TS 7.x 时需重新评估

### Constraint 2 — composite

tsconfig.json 使用 project references：

```json
{
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

因此：

tsconfig.app.json 必须包含：

```json
{
  "composite": true
}
```

tsconfig.node.json 必须包含：

```json
{
  "composite": true
}
```

否则 VSCode 会提示：`Referenced project must have setting "composite": true`

### Constraint 3 — emitDeclarationOnly

不要使用 `noEmit: true` 与 `composite` 组合。

当前项目必须使用：

```json
{
  "emitDeclarationOnly": true
}
```

避免：`Referenced project may not disable emit`

### Development Rule

未来任何 React 项目开发任务，涉及以下文件：

- tsconfig.json
- tsconfig.app.json
- tsconfig.node.json

修改前必须检查：

1. ignoreDeprecations 是否保留为 5.0（当前 TS 5.9.3 仅支持 "5.0"，不支持 "6.0"）
2. composite 是否保留为 true
3. emitDeclarationOnly 是否保留
4. @ 路径别名是否正常
5. vite.config.ts 中 alias 是否正常

禁止自动升级或重构 TS 配置。

------

# Critical Reminders

每次开始新任务前，必须先阅读 docs/ai/05_PROJECT_CONTEXT.md 中的当前活跃阶段和安全约束。

必须遵守阶段最终目标与边界总控。每个阶段开始前复述目标、允许范围、禁止事项、验收标准；每个阶段结束后检查是否越界、是否提前实现后续阶段能力。不得把多个阶段混在同一轮完成，不得用“顺便完成了某功能”替代阶段验收。

1. 当前 auto_wechat 已完成 P1-END-1 自动检测单次闭环演示版冻结，验收文档见 docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md
2. 测试电脑默认无源码，不得要求虚拟机运行 python 命令作为验收
3. 本地 Agent 名称为**小高AI微信助手**（exe：小高AI微信助手.exe），禁止使用"萌猫微信助手"
4. React 的本机 Agent 测试按钮必须调用浏览器所在电脑的 127.0.0.1:19000，不走 VITE_API_BASE_URL
5. 业务自动派单发送仍禁止，sent 必须为 false
6. React 离线提示应使用："未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手"
7. Bug 修复必须先做代码探索和根因确认，禁止仅凭现象就编写修复方案（详见 02_EXECUTION_RULES.md #17 BUG 修复前置探索原则）
8. 高风险逻辑必须强制写诊断日志，包含 stage、输入摘要、failure_stage，禁止只写"失败了"（详见 02_EXECUTION_RULES.md #19 高风险代码日志原则）
9. P1-END-1 后新窗口必须先阅读 docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md
10. 禁止绕过 task_id 指定执行机制，新建任务后必须按 task_id 执行当前任务
11. 诊断接口（search-debug 等）不得返回原始 UIA 对象，必须安全 JSON 序列化

------

## Current Task Focus and Bug-Fix Gate

1. Bug 修复前必须先澄清真实调用链、真实根因、涉及文件、修改范围、是否影响无关模块、是否可能引入回归。
2. 高风险逻辑必须写诊断日志，便于后续排查；不得只记录“失败了”。
3. 当前重点是 /agent/wechat/test、Local Agent 19000、微信搜索框自动点击诊断、search_focus_not_verified、_click_left_button / SetCursorPos / mouse_event、click_debug 诊断。
4. 除非用户明确批准，当前不应进入 OCR Reader、verify_search_text_in_search_box、search_text_not_verified、P0-5A WechatTask、React、发送逻辑。

# Mandatory Workflow

任何任务必须遵循：

理解需求
↓
阅读项目
↓
建立上下文
↓
分析影响面
↓
输出方案
↓
获得确认（如果需要）
↓
实现
↓
测试
↓
总结

禁止跳过阅读阶段直接编码。

------

# Required Reading Order

开始任务后按顺序阅读：

1. CLAUDE.md
2. docs/ai/01_READING_RULES.md
3. docs/ai/05_PROJECT_CONTEXT.md
4. docs/ai/02_EXECUTION_RULES.md
5. docs/ai/03_TESTING_RULES.md
6. docs/ai/04_OUTPUT_RULES.md

专题文档按需从 `docs/ai/README.md` 进入，不再默认遍历整个 `docs/ai` 目录。

归档目录：

```text
docs/ai/01_product_prd/          PRD 与需求差距
docs/ai/02_architecture/         架构与阶段迁移总方案
docs/ai/03_data_and_migration/   数据模型与迁移
docs/ai/04_interface_contracts/  接口契约与外部系统契约
docs/ai/05_acceptance/           测试计划、验收与检查清单
docs/ai/06_rag/                  RAG、Milvus、统一知识库
docs/ai/07_autoreply/            自动回复 gate、rollout、白名单
docs/ai/08_newcar/               NewCarProject 登录与权限
docs/ai/09_car_project/          car-porject-main 对接
docs/ai/10_local_agent_wechat/   Local Agent 与微信自动化
docs/ai/11_deployment_ops/       Docker、部署、OpenAPI、live-check
docs/ai/12_legacy_research/      历史计划与探索资料
```

------

# Reading Completion Gate

在完成以下问题之前禁止编码：

1. 当前需求属于哪个模块？
2. 当前调用链是什么？
3. 当前数据从哪里来？
4. 当前数据写到哪里去？
5. 当前权限在哪里校验？
6. 当前影响哪些模块？
7. 当前风险等级是什么？
8. 最小修改方案是什么？

如果无法回答：

继续阅读。

------

# High Risk Areas

以下区域属于高风险：

- Docker
- Docker Compose
- Nginx
- Environment Variables
- Database Migration
- Authentication
- RBAC
- File Storage
- Background Worker
- Deployment Scripts
- CI/CD

涉及以上区域：

必须先完成风险分析。

禁止直接修改。

------

# Coding Entry Condition

只有满足以下条件才能编码：

- 已完成项目阅读
- 已完成调用链分析
- 已完成影响面分析
- 已完成方案设计
- 已明确验证方案

否则继续阅读。

------

# Project Philosophy

AI 的首要职责不是写代码。

AI 的首要职责是理解项目。

理解错误：

后续全部错误。

理解正确：

编码只是执行。

因此：
Reading First.
Coding Later.

------

# P0-API-1 接口契约完成记录

更新时间：2026-06-15

接口契约文档：`docs/ai/04_interface_contracts/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`

关键结论：第一版产品化接口契约保留 `/webhook/douyin` 作为正式 webhook 入口，AI小高线索到小高AI微信助手推荐先采用拉取式边界或服务层模拟；Local Agent 兼容现有 `poll-and-execute` / `poll-and-detect`，后续需补齐生产验签迁移、NewCarProject 入口、商户后台、导出、状态回调和健康检查等接口实现方案。

下一步文档重点：Webhook 验签迁移技术方案与代码修改计划。

------

# P0-WEBHOOK-AUTH-1 Webhook 验签迁移技术方案完成记录

更新时间：2026-06-15

技术方案文档：`docs/ai/04_interface_contracts/10_WEBHOOK_AUTH_MIGRATION.md`

关键结论：douyinAPI 的验签实现可作为签名计算、原始 body、timestamp 校验和测试样例参考，但不能作为 auto_wechat 正式生产依赖；auto_wechat 当前 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 只允许作为开发 / 联调兼容，生产环境后续必须引入环境识别并强制验签。

下一步文档重点：代码修改计划与测试验收计划。

------

# P0-CODEPLAN-1 产品化代码修改计划完成记录

更新时间：2026-06-15

代码修改计划文档：`docs/ai/12_legacy_research/11_CODE_PLAN_AUTO_WECHAT.md`

关键结论：本轮只输出代码修改计划，不修改业务代码。后续产品化代码建议分阶段执行：先处理 Webhook 生产验签和 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 迁移风险，再补联系方式提取、原始事件 / 有效线索规则、数据模型字段、状态流转、customer_id 预留、Local Agent 回归、前端接口与导出。执行前需要先确认生产签名头、SECRET_KEY 配置、数据库迁移策略和 NewCarProject 对接字段。

------

# P0-CODEPLAN-1A 日志模板探索补充记录

更新时间：2026-06-15

只读探索路径：`D:\zws\ask_next_Project\log-template`

探索对象：

```text
logging_config.py
logging_config.py 使用说明.md
```

关键结论：该日志模板提供 `setup_logging()`、`get_module_logger()`、彩色控制台、常规日志、ERROR 独立日志、按天轮转和 `LOG_LEVEL` 控制，适合作为 auto_wechat 后续日志基础设施参考。

限制：模板没有 request_id / trace_id、FastAPI middleware、全局异常 handler、contextvars、响应头回传、敏感信息脱敏 filter，也没有 auto_wechat 所需的 `customer_id`、`lead_id`、`task_id`、`agent_client_id`、`source_path`、`stage`、`failure_stage` 等诊断字段。

后续执行前必须先确认：

1. 日志目录和 Local Agent exe 落盘位置。
2. 运行日志和错误日志保留周期。
3. request_id / trace_id 字段名、生成规则、透传规则和响应头名称。
4. Authorization、cookie、token、SECRET_KEY、手机号、微信号、open_id、server_message_id、原始 body 的脱敏规则。
5. FastAPI middleware、exception handler、request state / contextvars 的接入方式。
6. 是否采用纯文本 key-value 日志还是 JSON Lines。

本轮只补充日志要求和执行前决策；不得据此直接复制日志代码，不得顺手修改业务代码、配置默认值、接口、数据库模型、测试或依赖。

------

# P0-TESTPLAN-1 测试验收计划完成记录

更新时间：2026-06-15

测试验收计划文档：`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

关键结论：第一版产品化测试验收范围覆盖 Webhook 生产验签、原始 body 签名一致性、联系方式提取、有效线索生成、invalid 展示与导出、状态流转、销售分配、超时重分配、Local Agent 发送 / 检测互斥、失败回写、日志脱敏、数据迁移兼容、前端接口和导出。正式验收不以免验签为通过口径；Local Agent 真机验收必须保持 `sent=false`、检测只读、不粘贴、不发送、不按 Enter。

本轮只输出测试验收计划；不得顺手修改业务代码、测试代码、配置默认值、接口实现、数据库模型或依赖，不得启动服务，不得执行迁移或真机微信自动化。

------

# P0-DEV-A1 Webhook 验签生产安全改造完成记录

更新时间：2026-06-15

本轮已进入代码阶段，但只执行 Webhook 验签生产安全小补丁。

关键结论：

1. `APP_ENV` 已作为环境识别变量加入配置，默认值为 `development`。
2. development 环境继续允许 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false`，用于本地开发 / 联调。
3. production 环境强制 webhook 验签，`DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 不再能静默放行。
4. production 环境缺少 `DY_SECRET_KEY` 时，webhook 请求拒绝，不进入业务事件处理。
5. `/webhook/douyin` 和 `/integrations/douyin/webhook` 继续共用 `_handle_douyin_webhook()`，验签逻辑一致。
6. 签名算法保持 `sha256Hex(SECRET_KEY + body + "-" + timestamp)` 不变。
7. 本轮没有修改数据库模型、没有执行迁移、没有改 Local Agent 自动化逻辑、没有引入新依赖。

------

# P0-DEV-E1 原始事件 / invalid 只读查询接口完成记录

更新时间：2026-06-15

完成状态：P0-DEV-E1 已完成。

已新增只读接口：

1. `GET /webhook-events`
2. `GET /webhook-events/{event_id}`

关键结论：

1. 数据来源为现有 `douyin_webhook_events`。
2. 当前不新增字段、不迁移数据库。
3. 当前通过解析 `raw_body` 和现有字段推导事件展示状态：
   - `duplicate_event`
   - `valid_lead`
   - `non_lead_event`
   - `invalid_content`
   - `non_text_message`
   - `invalid_contact`
   - `unknown`
4. `/leads` 保持只展示有效线索。
5. invalid / 原始事件通过 `/webhook-events` 单独展示。
6. 全量测试结果：`722 passed, 149 warnings`。
7. warnings 为既有 deprecation warnings。
8. 本轮未修改 webhook 验签、webhook 写入、contact_extractor、有效线索生成规则、Local Agent、数据库模型、依赖。
