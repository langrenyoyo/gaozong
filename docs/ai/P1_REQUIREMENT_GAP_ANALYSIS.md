# 当前代码能力与一期需求差异探索报告

更新时间：2026-06-18

> ## 状态更新（2026-06-19）
>
> 本报告为截至 `244a93b` 的差异分析快照。以下条目已在后续提交中**闭环或基本闭环**，最新结论以 `docs/ai/P1_REQUIREMENT_ALIGNMENT_REPORT.md`（HEAD `2d8986b`）为准，不再以下表"未实现/部分实现"的旧表述为准。
>
> | 原缺口 | 闭环提交 | 新结论 |
> |---|---|---|
> | 线索商户隔离（`douyin_leads` 缺 `merchant_id` / `tenant_id`） | `971707b` + migration `0011_leads_session_isolation.sql` | **已闭环** |
> | 抖音授权 open_id 绑定当前商户 | `399f772` / `2ecac8e` | **已闭环** |
> | 企业号绑定智能体真实上下文（9000 权威源注入 agent_config） | `d33620d` / `fc8c1be` / `7df1875` | **已闭环** |
> | 小高算力商户页 / 超管算力配置前端 | `60ebeca` / `a3b0ebe` / `88ea1e5` | **基本闭环**（真实支付安全暂缓，见 `P1_COMPUTE_ACCEPTANCE.md`） |
> | 历史 NULL 线索处理策略 | `f19d722` / `P1_END_3_LEGACY_LEADS.md` | **已文档化收尾**（零代码） |
>
> 本报告中其余"部分实现 / 未实现"项（登录真实态、超管商户 / 违禁词 / 回访话术、微信助手规则引擎、线索状态枚举语义、表情 / 视频 / 文件工具栏等）截至 `2d8986b` **仍未闭环**，需对照 `P1_REQUIREMENT_ALIGNMENT_REPORT.md` 逐项确认。
>
> 另：`fc9663c` / `30178d6` / `ae55e6c` / `a70609d` / `22c1013` / `2d8986b` 引入的 RAG 向量检索 / 知识分类能力，经 `P1_REQUIREMENT_ALIGNMENT_REPORT.md` 评定为**超出一期对外需求**，已标注为发散 / 超前项，不计入一期验收口径。

本报告基于《需求文档-小高AI系统一期（对外）.md》和当前 `auto_wechat` 代码只读探索结果整理。本轮只固化文档和 P0 技术方案，不代表已经进入业务功能开发阶段。

## 0. Git 快照与边界

### 0.1 本轮开始 Git 快照

```text
git status --short
?? scripts/seed_dev_data.py
?? tests/test_seed_dev_data.py

git branch --show-current
master

git log --oneline -n 30
244a93b feat: 接入9100 LLM算力消耗上报
d034382 docs: 收口抖音企业号绑定智能体一期文档
fc8c1be feat: 代理注入真实智能体配置到9100
adacf8b feat: 实现小高算力一期后端接口
8d4fc40 feat: 解除9100正式回复建议对mock绑定依赖
36b006e feat: 补齐AI小高线索管理能力
9dc3b2a feat: 接入抖音企业号绑定智能体前端控件
eb17d3b feat: 线索分配重分配写入跟进记录
f5661b2 feat: 添加小高算力一期数据库基础
836da38 feat: 实现线索跟进记录与线索管理后端基础
d33620d feat: 实现抖音企业号绑定智能体后端基础能力
6e21f89 PRD：一期最终PRD更新
3fa4b46 feat: 实现AI小高智能体最小管理能力
ecc64d9 feat: 增加抖音AI客服账号智能体绑定校验
1b68609 fix(frontend): 统一无时区时间展示
214ed47 docs: 新增 P1 前端联调整体验收记录
a523b16 feat: 前端接入抖音图片上传入口
f74bdbb feat: 前端AI回复建议切换到9000可信代理
afc8258 feat: 新增抖音AI客服可信代理接口
2f0a49c fix: 按真实资源链接控制抖音资源下载入口
e64ac22 feat: 新增 NewCarProject 登录权限上下文门面
37c2910 docs: 新增 NewCarProject 登录权限契约待确认文档
533d803 feat: 接入抖音私信资源下载入口
1ac4a44 fix: 优化人工确认发送入口可见性
3e775a5 fix: 人工确认发送按钮选中会话后可见
00c4682 feat: 接入抖音人工确认文本发送入口
8eb52ed feat: 预留抖音AI客服 Agent Runtime 关闭态骨架
da124c5 docs: 新增 P1 OpenAPI 验收与前端入口设计
34cd08f docs: 固化服务边界和 Agent Runtime 架构
cb19393 refactor: 统一抖音 OpenAPI client 和安全错误处理
```

### 0.2 已有未提交改动

本轮开始时存在以下未跟踪文件，判断为其他会话已有改动，本报告不触碰：

- `scripts/seed_dev_data.py`
- `tests/test_seed_dev_data.py`

上一轮提到的 `compute_usage` 相关文件已经进入提交 `244a93b feat: 接入9100 LLM算力消耗上报`，因此本报告不再把它们标记为未提交改动。

### 0.3 本轮安全边界

- 不运行真实微信自动化，不发送微信消息。
- 不运行真实抖音发送，不发送抖音私信。
- 不调用真实 LLM、Embedding、支付或生产数据库。
- 19000 Local Agent 只识别代码能力，不做真机动作。
- 抖音 AI 客服 `auto_send=false` 是当前必须保留的安全边界，不视为缺陷。
- 微信链路 `sent=false`、`paste_only`、`read_only`、人工确认边界必须保留。
- 不信任前端传入 `agent_config`，正式链路继续由 9000 注入可信智能体配置给 9100。

## 1. 探索结论摘要

1. 9000 主后端已经具备线索、销售分配、微信任务、回复检测、抖音企业号绑定智能体、小高算力后端和 NewCarProject 鉴权门面的部分能力。
2. 9100 抖音 AI 客服已经具备多账号工作台、RAG 检索、LLM 回复建议和 9000 注入可信智能体配置的技术底座，但不是自动发送系统。
3. frontend 已有主要工作台页面，但登录、路由权限、算力页面和多数超管页面仍未形成真实闭环。
4. 19000 小高AI微信助手是 Windows 本地微信 UI 辅助与只读检测代理，不是完整规则引擎或 LLM Agent。
5. 小高算力后端接口与模型已经完成一期基础，但商户端和超管前端仍是“真实接口暂未接入”占位。
6. 登录与权限最大缺口是 NewCarProject 真实契约未确定，前端仍是本地账号识别。
7. 多商户隔离最大风险是 `douyin_leads` 缺 `merchant_id` / `tenant_id`，线索列表无法做强隔离。
8. 超级管理员功能大多是页面占位或前端静态能力，缺真实后端模型、接口和测试。
9. 统一知识库训练还不是完整产品页；9100 RAG 是底座，不能等同于“训练中心”已经完成。
10. 下一步优先补齐顺序建议：登录契约确认、权限闭环、线索商户隔离设计、算力前端接入。

## 2. 当前代码能力地图

| 模块 | 当前页面/接口 | 后端能力 | 前端能力 | 测试覆盖 | 结论 |
| -- | ------- | ---- | ---- | ---- | -- |
| 登录模块 | `GET /auth/me`、`GET /auth/callback`；`frontend/src/pages/Login.tsx` | `app/auth/newcar_client.py` 有 NewCarProject 门面和 mock 上下文；未真实调用 `/api/login` | 登录页本地识别 `admin/operation01/finance01/merchant`，有记住账号 UI | `tests/test_auth_context.py` | 部分实现 |
| 角色与权限 | `app/auth/context.py`、`app/auth/dependencies.py` | 有 `RequestContext`、`require_permission`、`require_any_permission`、`require_merchant_access`，覆盖不完整 | `SideNav.tsx` 按 `user.role !== merchant` 切菜单；`App.tsx` 只有少量路由 | `tests/test_auth_context.py`，局部接口测试 | 部分实现 |
| 抖音 AI 客服 | 9000 `/integrations/douyin-ai-cs/*`；9100 `apps/xg_douyin_ai_cs/*`；前端 `DouyinAiCsWorkbenchPage.tsx` | 9000 代理注入可信 agent；9100 RAG/LLM 回复建议，`auto_send=False` | 工作台页面已接入账号、会话、回复建议、人工发送入口 | `tests/test_xg_douyin_ai_cs_app.py`、相关代理测试 | 部分实现，主链路较完整 |
| AI小高线索 | `/leads`；`app/routers/leads.py` | 线索列表、详情、分配、评分、跟进记录基础具备；`DouyinLead` 缺商户字段 | `LeadsManagement` 已有线索页面和筛选/详情能力 | `tests/test_leads_management.py` 等 | 部分实现 |
| AI小高智能体 | `/agents`；`app/routers/agents.py` | 智能体 CRUD、训练聊天占位、商户归属字段具备 | 智能体页面和企业号绑定控件已有 | 智能体、企业号绑定相关测试 | 部分实现 |
| 抖音企业号管理 | `/integrations/douyin/accounts` | 绑定权威来源在 9000；绑定、解绑、取消授权本地状态、删除软状态具备 | 工作台已接账号 Agent 绑定 | 账号绑定和代理测试 | 部分实现 |
| 微信助手 / Local Agent | `/wechat-tasks`、`app/local_agent_main.py`、前端 `/ai-agent` | 任务队列、`poll-and-execute`、`poll-and-detect`、`paste_only`、只读检测具备 | 微信助手页显示配置占位、任务队列、本机 Agent 联调 | `tests/test_p0_main_5b_poll_and_execute.py`、`tests/test_p1_auto_1c_poll_and_detect.py` | 部分实现，非规则引擎 |
| 小高算力 | `/compute/*`、`/admin/compute/*`、`/internal/compute/usage` | 余额、流水、套餐、mock 订单、管理员充值/发放、内部 usage 已有 | `ComputeCenter.tsx`、`SuperComputeConfig.tsx` 仍是未接入占位 | `tests/test_compute_models.py`、`tests/test_compute_service.py`、`tests/test_compute_router.py`、`tests/test_compute_usage_client.py` | 后端基本完成，前端缺失 |
| 超级管理员 | 多个 `frontend/src/pages/Super*.tsx` | 仅算力和企业号/智能体部分有后端；商户、禁用词、话术、账号等缺真实接口 | 多数页面显示真实接口暂未接入或静态能力 | 主要缺后端测试 | 未实现/部分实现 |
| 统一知识库训练 | 9100 `/rag`、`/ai_reply`；9000 `/agents/{id}/training-chat` | 9100 有 RAG repository；9000 智能体知识库多为字段，未形成统一训练中心 | 智能体页/训练聊天局部能力，不是完整训练产品页 | 9100 RAG/LLM 测试 | 部分实现 |

## 3. 需求差异矩阵

| 需求模块 | 需求点 | 当前状态 | 证据代码位置 | 差异说明 | 建议优先级 |
| ---- | --- | ---- | ------ | ---- | ----- |
| 登录模块 | 账号密码登录 | 未实现 | `frontend/src/pages/Login.tsx`；`app/auth/newcar_client.py` | 前端未调用真实登录 API；后端门面只 introspect token/code/cookie，不处理账号密码 | P0 |
| 登录模块 | 记住账号 | 部分实现 | `frontend/src/pages/Login.tsx` | 只有 UI 状态，未见持久化存储和真实账号恢复 | P2 |
| 登录模块 | 角色识别 merchant / super_admin | 部分实现 | `frontend/src/pages/Login.tsx`；`app/auth/context.py` | 前端写死账号映射；后端上下文支持角色但依赖 mock 或外部契约 | P0 |
| 登录模块 | 登录后按权限跳转 | 部分实现 | `frontend/src/App.tsx` | 统一跳转 `/douyin-ai-cs`，未基于权限字典选择首页 | P1 |
| 登录模块 | 对接 NewCarProject `/api/login` | 未实现 | `app/auth/newcar_client.py` | 注释明确 P0 不绑定真实字段契约，未调用真实接口 | P0 |
| 登录模块 | 权限字典支持 auto_wechat 功能 | 部分实现 | `app/auth/newcar_client.py`；`app/auth/dependencies.py` | mock 包含部分权限码，缺 NewCarProject 字典映射 | P0 |
| 角色与权限 | merchant 可见功能 | 部分实现 | `frontend/src/components/SideNav.tsx` | 菜单按本地角色区分，非权限字典驱动 | P1 |
| 角色与权限 | super_admin 可见功能 | 部分实现 | `frontend/src/components/SideNav.tsx`；`frontend/src/pages/Index.tsx` | 超管菜单少量独立，页面多为占位 | P1 |
| 角色与权限 | 前端路由隔离 | 部分实现 | `frontend/src/App.tsx` | 有 React Router，但只注册 `/`、`/douyin-ai-cs`、`/douyin-ai-cs-test`，多数页面靠 `Index` 内部状态切换 | P1 |
| 角色与权限 | 后端接口商户/管理员鉴权 | 部分实现 | `app/routers/compute.py`；`app/routers/douyin_accounts.py`；`app/routers/leads.py` | compute、douyin account 较完整；leads 只取 context 但受模型缺商户字段限制 | P0 |
| 角色与权限 | merchant_id / tenant_id 贯穿 | 部分实现 | `app/models.py` | `DouyinAuthorizedAccount`、`AiAgent`、compute 有商户字段；`DouyinLead` 无商户字段 | P0 |
| 抖音AI客服 | 企业号列表 | 部分实现 | `app/routers/douyin_accounts.py`；`DouyinAiCsWorkbenchPage.tsx` | 9000 列表按可信商户过滤；真实授权完整异常处理仍不足 | P1 |
| 抖音AI客服 | 会话列表 | 部分实现 | `apps/xg_douyin_ai_cs`；`DouyinAiCsWorkbenchPage.tsx` | 9100 有会话工作台；多商户隔离依赖 9000 注入上下文 | P1 |
| 抖音AI客服 | 客户标签 | 部分实现 | `DouyinAiCsWorkbenchPage.tsx`；9100 schemas/services | 页面与数据结构有标签雏形，需复核是否完全覆盖“需人工、高意向、已留资、待回访”状态机 | P1 |
| 抖音AI客服 | 聊天面板 | 已实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` | 已形成工作台体验 | P1 |
| 抖音AI客服 | AI/人工/用户消息 | 部分实现 | `apps/xg_douyin_ai_cs`；`DouyinAiCsWorkbenchPage.tsx` | 有消息展示和建议，生产消息来源与状态仍需验收 | P1 |
| 抖音AI客服 | AI托管/人工接管 | 部分实现 | `reply_decision_service.py`；`DouyinAiCsWorkbenchPage.tsx` | 回复建议具备，`auto_send=False`，不是 AI 自动托管发送 | P0 |
| 抖音AI客服 | 图片/视频/文件 | 部分实现 | `frontend/src/pages/DouyinAiCsWorkbenchPage.tsx`；资源下载相关提交 | 已有资源入口，但完整发送和上游资源能力需验收 | P2 |
| 抖音AI客服 | 回复建议、手动发送、自动发送边界 | 部分实现 | `apps/xg_douyin_ai_cs/services/reply_decision_service.py`；`frontend/src/pages/DouyinAiCsWorkbenchPage.tsx` | 回复建议和人工入口有；自动发送必须保持关闭 | P0 |
| 抖音AI客服 | 9100 与 9000 调用链 | 部分实现 | `app/routers/douyin_ai_cs_proxy.py`；`reply_decision_service.py` | 9000 可信代理到 9100 已有，内部契约仍需稳定 | P0 |
| 抖音AI客服 | 真实智能体配置绑定 | 部分实现 | `app/routers/douyin_accounts.py`；`app/routers/douyin_ai_cs_proxy.py` | 9000 注入真实 `AiAgent`，9100 消费上下文 | P0 |
| 抖音AI客服 | 禁止自动发送安全边界 | 已实现 | `reply_decision_service.py` 多处 `auto_send=False` | 当前安全边界明确，不应作为缺陷处理 | P0 |
| 线索管理 | `/leads` 页面 | 已实现 | `frontend/src/pages/LeadsManagement.tsx`；`app/routers/leads.py` | 页面和接口存在 | P1 |
| 线索管理 | 统计卡片/筛选/列表字段/详情 | 部分实现 | `LeadsManagement.tsx`；`app/routers/leads.py`；`app/services/lead_management_service.py` | 基础能力已有，字段和需求清单需逐项补齐 | P1 |
| 线索管理 | 线索评分 | 部分实现 | `app/services/lead_management_service.py`；`tests/test_leads_management.py` | 有评分基础，规则需与 PRD 再对齐 | P1 |
| 线索管理 | 销售跟进时间线 | 部分实现 | `app/services/lead_management_service.py`；`tests/test_leads_management.py` | 已有跟进记录，但完整事件来源仍需统一 | P1 |
| 线索管理 | 重新分配弹窗和备注 | 部分实现 | `app/services/lead_management_service.py`；`frontend/src/pages/LeadsManagement.tsx` | 后端已有重分配记录，前端体验需验收 | P1 |
| 线索管理 | 状态流转 | 部分实现 | `app/models.py`；`app/routers/leads.py` | 现有状态与需求“新线索→跟进中→已留资→已成交/已失效”不完全一致 | P0 |
| 智能体 | 创建/编辑/删除/列表卡片 | 部分实现 | `app/routers/agents.py`；前端智能体页面 | 最小 CRUD 已有，前端和后端需验收字段完整性 | P1 |
| 智能体 | 提示词/知识库 | 部分实现 | `app/models.py` `AiAgent`；`app/routers/agents.py` | 9000 侧多为字段；9100 有 RAG 技术底座 | P1 |
| 智能体 | 与抖音企业号绑定 | 部分实现 | `app/models.py` `DouyinAccountAgentBinding`；`app/routers/douyin_accounts.py` | 绑定权威源已在 9000 | P0 |
| 智能体 | 被 9100 回复建议真实使用 | 部分实现 | `app/routers/douyin_ai_cs_proxy.py`；`reply_decision_service.py` | 9000 注入 agent_config，9100 消费，但 RAG scope 后续仍需升级 | P0 |
| 智能体 | RAG/embedding/search | 部分实现 | `apps/xg_douyin_ai_cs/rag/repository.py`；`apps/xg_douyin_ai_cs/routers/rag.py` | 9100 有 RAG；不等于统一知识库训练产品页 | P1 |
| 企业号管理 | 添加企业号/授权链接/二维码 | 部分实现 | `app/routers/douyin_accounts.py`；前端工作台 | 应用内授权已有，完整二维码/异常闭环需确认 | P1 |
| 企业号管理 | 授权成功同步账号信息 | 部分实现 | `DouyinAuthorizedAccount`；相关 OpenAPI 提交 | 有账号表和授权状态，但真实上游回调链需继续验收 | P1 |
| 企业号管理 | 列表字段和绑定智能体 | 部分实现 | `app/routers/douyin_accounts.py` | 返回账号信息与绑定摘要；字段需与 PRD 最终清单对齐 | P1 |
| 企业号管理 | 取消授权/删除账号 | 部分实现 | `app/routers/douyin_accounts.py` | 本地软状态有；真实上游取消授权 `upstream_cancel_supported=false` | P1 |
| 企业号管理 | 9000 权威源/9100 可信消费 | 已实现 | `app/routers/douyin_ai_cs_proxy.py`；`reply_decision_service.py` | 当前边界正确，应保留 | P0 |
| 微信代理 | `/ai-agent` 页面 | 部分实现 | `frontend/src/pages/WechatAgent.tsx` | 页面存在，但规则配置真实接口未接入 | P1 |
| 微信代理 | 客户端状态/历史记录/任务队列 | 部分实现 | `WechatAgent.tsx`；`frontend/src/api/localWechatAgent.ts` | Local Agent 联调、任务队列、检测记录已有 | P1 |
| 微信代理 | 配置列表、添加、搜索、启停、规则类型 | 未实现/部分实现 | `WechatAgent.tsx` | 页面明确提示“规则配置暂未接入真实接口” | P1 |
| 微信代理 | 启动微信测试 | 部分实现 | `app/local_agent_main.py`；`LocalWechatAgentTestPanel.tsx` | 19000 有测试/诊断接口，但不代表完整规则引擎 | P1 |
| 微信代理 | 与 19000 能力差异 | 部分实现 | `app/local_agent_main.py` | 19000 是 UI 辅助、任务执行和只读检测，不是后台规则引擎 | P0 |
| 小高算力 | `/compute` 页面 | 部分实现 | `frontend/src/pages/ComputeCenter.tsx` | 页面存在但显示真实接口暂未接入 | P1 |
| 小高算力 | 后端余额/消耗/明细/套餐/充值 | 部分实现 | `app/routers/compute.py`；`app/services/compute_service.py` | 后端一期接口已具备；充值是 mock，不真实支付 | P1 |
| 小高算力 | 微信/支付宝支付/付款码/订单号 | 部分实现 | `app/services/compute_service.py` | 仅生成 mock 订单号和 `mock://pay`，不接真实支付 | P2 |
| 小高算力 | 管理员套餐配置/充值/发放 | 部分实现 | `app/routers/compute.py` | 后端有，前端未接真实接口 | P1 |
| 小高算力 | 余额不足拦截 | 未实现 | `app/services/compute_service.py` | 注释明确一期不做余额不足拦截，可负余额 | P2 |
| 小高算力 | usage 记账接口 | 已实现 | `/internal/compute/usage`；`compute_usage_client.py` | 9100 LLM 成功后可上报，失败不影响回复 | P1 |
| 超级管理员 | 商户管理、新增/编辑、延期、启停、重置密码 | 未实现 | `frontend/src/pages/SuperMerchantManagement.tsx` | 页面提示真实接口暂未接入 | P1 |
| 超级管理员 | 违禁词、回访提示词 | 未实现 | `SuperForbiddenWords.tsx`；`SuperFollowUpPrompts.tsx` | 页面提示真实接口暂未接入 | P2 |
| 超级管理员 | AI回复记录 | 部分实现 | `SuperAiReplyRecords.tsx`；9100 LLM log | 前端有页面，后端查询闭环需继续确认 | P2 |
| 超级管理员 | 算力配置 | 部分实现 | `SuperComputeConfig.tsx`；`app/routers/compute.py` | 后端有，前端未接 | P1 |
| 超级管理员 | 管理员账号管理 | 部分实现/未实现 | `SuperAdminAccounts.tsx` | 前端页面存在，真实后端不足 | P2 |
| 统一知识库训练 | 训练页面 | 部分实现 | 智能体页面；`app/routers/agents.py` `training-chat` | 不等于完整训练中心 | P1 |
| 统一知识库训练 | 欢迎消息、用户/AI交互 | 部分实现 | `app/routers/agents.py`；前端智能体页 | 有训练聊天雏形，产品化不足 | P2 |
| 统一知识库训练 | 真实知识库/RAG/embedding 打通 | 部分实现 | `apps/xg_douyin_ai_cs/rag/*`；`reply_decision_service.py` | 9100 RAG 可用，9000 智能体知识库与统一训练闭环未完全打通 | P1 |

## 4. 关键调用链说明

### 4.1 登录与权限链路

```text
frontend Login.tsx
  → 当前本地账号映射生成 AppUser
  → App.tsx 保存内存 user
  → Index.tsx / SideNav.tsx 按 role 切换菜单

真实后端预留链路：
NewCarProject token/code/cookie
  → app/auth/dependencies.py
  → NewCarProjectAuthClient
  → RequestContext
  → require_permission / require_any_permission / require_merchant_access
  → 业务接口
```

证据：`frontend/src/pages/Login.tsx`、`frontend/src/App.tsx`、`frontend/src/components/SideNav.tsx`、`app/auth/newcar_client.py`、`app/auth/context.py`、`app/auth/dependencies.py`、`app/routers/auth.py`。

### 4.2 抖音企业号绑定链路

```text
frontend DouyinAiCsWorkbenchPage
  → 9000 /integrations/douyin/accounts
  → RequestContext.merchant_id
  → DouyinAuthorizedAccount 按 merchant_id 过滤
  → DouyinAccountAgentBinding 写入绑定
  → 9000 成为绑定权威来源
```

证据：`app/routers/douyin_accounts.py`、`app/models.py` `DouyinAuthorizedAccount` / `DouyinAccountAgentBinding`、`frontend/src/pages/DouyinAiCsWorkbenchPage.tsx`。

### 4.3 抖音会话 AI 回复建议链路

```text
frontend 工作台选择会话
  → 9000 /integrations/douyin-ai-cs/conversations/{id}/reply-suggestion
  → 9000 校验企业号归属、授权状态、Agent 归属和绑定
  → 9000 注入可信 agent_config
  → 9100 apps/xg_douyin_ai_cs
  → RAG search + LLM chat
  → 返回 reply_text、manual_required、auto_send=false
  → LLM 成功时可上报 /internal/compute/usage
```

证据：`app/routers/douyin_ai_cs_proxy.py`、`apps/xg_douyin_ai_cs/services/reply_decision_service.py`、`apps/xg_douyin_ai_cs/services/compute_usage_client.py`。

### 4.4 线索管理链路

```text
抖音 webhook / 同步
  → app/integrations/douyin_webhook.py
  → douyin_webhook_events 原始事件
  → douyin_leads 有效线索
  → app/routers/leads.py / app/services/lead_management_service.py
  → 前端 /leads
  → 分配/重分配/跟进记录/评分
```

当前关键差异：`douyin_leads` 仍缺 `merchant_id` / `tenant_id`，不能保证多商户强隔离。

证据：`app/models.py` `DouyinLead`、`app/routers/leads.py`、`app/services/lead_management_service.py`、`frontend/src/pages/LeadsManagement.tsx`。

### 4.5 算力消耗/充值链路

```text
商户端：
RequestContext.merchant_id
  → /compute/summary
  → /compute/transactions
  → /compute/packages
  → /compute/recharge-orders（mock，不到账）

管理员端：
super_admin
  → /admin/compute/packages
  → /admin/merchants/{merchant_id}/compute/recharge
  → /admin/merchants/{merchant_id}/compute/grant-package

内部记账：
9100 LLM 成功
  → ComputeUsageClient
  → 9000 /internal/compute/usage
  → compute_transactions consume
```

证据：`app/routers/compute.py`、`app/services/compute_service.py`、`app/models.py` `Compute*`、`apps/xg_douyin_ai_cs/services/compute_usage_client.py`、`tests/test_compute_router.py`。

### 4.6 微信 Local Agent 链路

```text
9000 /wechat-tasks 创建 notify_sales / detect_reply
  → React 调浏览器本机 127.0.0.1:19000
  → /agent/tasks/poll-and-execute 按 task_id 执行 notify_sales
  → 只允许 Aw3 + paste_only + sent=false
  → 9000 回写 pasted
  → 自动创建 detect_reply task
  → /agent/tasks/poll-and-detect 按 task_id 只读检测
  → action.sent=false / action.pasted=false
  → 9000 回写检测结果
```

证据：`app/routers/wechat_tasks.py`、`app/services/wechat_task_service.py`、`app/local_agent_main.py`、`frontend/src/components/WechatTaskPanel.tsx`、`tests/test_p0_main_5b_poll_and_execute.py`、`tests/test_p1_auto_1c_poll_and_detect.py`。

## 5. 已实现但与需求不完全一致的地方

- 状态枚举不一致：`DouyinLead.status` 当前仍偏 `pending/assigned/replied/timeout/closed` 等旧语义，需求里线索管理还要求“新线索→跟进中→已留资→已成交/已失效”。证据：`app/models.py`、`app/routers/leads.py`。
- 前端路由隔离不足：`App.tsx` 只有少量真实路由，多数页面靠 `Index.tsx` 内部 `activeNav` 切换，无法形成完整 URL 级权限隔离。证据：`frontend/src/App.tsx`、`frontend/src/pages/Index.tsx`。
- 前端有页面但后端未接：`SuperMerchantManagement.tsx`、`SuperForbiddenWords.tsx`、`SuperFollowUpPrompts.tsx`、`ComputeCenter.tsx`、`SuperComputeConfig.tsx` 多处提示真实接口暂未接入。
- 后端有接口但前端未接：小高算力后端 `/compute/*`、`/admin/compute/*` 已有，前端仍是占位。证据：`app/routers/compute.py`、`frontend/src/pages/ComputeCenter.tsx`、`frontend/src/pages/SuperComputeConfig.tsx`。
- 测试覆盖和生产链路边界不同：compute 有后端测试，前端未接；9100 LLM 与 usage 测试通过 mock，不代表真实 LLM 或生产计费已验收。证据：`tests/test_compute_router.py`、`tests/test_compute_usage_client.py`、`tests/test_xg_douyin_ai_cs_app.py`。
- mock 能力边界：登录、新能源上游契约、充值支付、部分超管页面仍是 mock 或占位。证据：`app/auth/newcar_client.py`、`app/services/compute_service.py`、相关 `frontend/src/pages/Super*.tsx`。
- 9000 与 9100 已打通可信 `agent_config`，但不能信任前端传入配置；后续必须继续由 9000 校验并注入。证据：`app/routers/douyin_ai_cs_proxy.py`、`reply_decision_service.py`。
- 微信 Local Agent 能力是 UI 辅助与检测，不是完整规则引擎；`WechatAgent.tsx` 明确规则配置暂未接入真实接口。证据：`frontend/src/pages/WechatAgent.tsx`、`app/local_agent_main.py`。

## 6. 明显未实现能力清单

| 模块 | 缺失能力 | 建议任务名 |
| -- | -- | -- |
| 登录 | NewCarProject 账号密码登录、token/cookie 字段解析、权限字典映射 | P1-GAP-LOGIN-1 |
| 权限 | 前端权限字典菜单、路由级隔离、后端接口全量权限审计 | P1-GAP-PERMISSION-1 |
| 线索 | `douyin_leads` 商户隔离、历史数据归属迁移、webhook 入库商户识别 | P1-GAP-LEADS-TENANT-1 |
| 算力 | 商户端和超管端前端真实 API 接入 | P1-GAP-COMPUTE-FE-1 |
| 超管 | 商户管理、禁用词、回访话术、管理员账号真实后端 | P1-GAP-ADMIN-1 |
| 微信助手 | 配置列表、规则类型、启停、历史规则引擎 | P1-GAP-WECHAT-RULE-1 |
| 知识库 | 统一训练中心、知识库版本、embedding/RAG 与 9000 智能体闭环 | P1-GAP-KB-1 |
| 企业号 | 上游真实取消授权、授权异常处理、二维码/授权状态完整验收 | P1-GAP-DY-ACCOUNT-1 |

## 7. 不建议现在做的内容

- 不建议现在放开抖音自动发送。当前 `reply_decision_service.py` 全路径 `auto_send=False` 是安全边界。
- 不建议现在放开微信自动发送。当前 `sent=false`、`paste_only`、`read_only`、`Aw3` 门禁仍是演示版安全边界。
- 不建议现在接真实支付。`create_mock_recharge_order()` 明确只生成 mock 订单号，不到账、不写流水。
- 不建议现在执行生产数据库自动迁移。`douyin_leads` 商户隔离涉及历史数据归属，需要先做设计和回滚方案。
- 不建议现在做无人工确认的微信 UI 自动化规则引擎。Local Agent 仍需前台窗口、OCR、联系人验证和运行锁保护。
- 不建议接未验签公网 webhook 或放松生产验签策略。生产环境必须明确 `APP_ENV`、`DY_SECRET_KEY` 和验签边界。
- 不建议信任前端传入 `merchant_id` 或 `agent_config`。9000 必须继续作为可信上下文注入方。

## 8. 后续开发任务拆分建议

| 任务编号 | 任务名称 | 目标 | 修改范围 | 风险 | 验收方式 |
| ---- | ---- | -- | ---- | -- | ---- |
| P1-GAP-LOGIN-1 | NewCarProject 登录接入 | 确认外部契约后接入真实登录态 | `app/auth/*`、`app/routers/auth.py`、`frontend/src/pages/Login.tsx`、API 客户端 | HIGH | mock 契约测试、401/403 测试、登录跳转手工验收 |
| P1-GAP-PERMISSION-1 | 权限菜单与路由隔离 | 前端按权限字典渲染菜单，后端关键接口权限闭环 | `frontend/src/App.tsx`、`SideNav.tsx`、`Index.tsx`、`app/auth/*`、routers | HIGH | 不同角色前后端越权测试 |
| P1-GAP-LEADS-TENANT-1 | 线索商户隔离设计与落地 | 为线索和原始事件补齐可信商户归属 | `app/models.py`、migrations、webhook、leads service/router | HIGH | 迁移 dry-run、历史数据兼容、多商户不可见测试 |
| P1-GAP-COMPUTE-FE-1 | 小高算力前端真实接入 | 商户端和超管端接后端 compute API | `frontend/src/api/*`、`ComputeCenter.tsx`、`SuperComputeConfig.tsx` | MEDIUM | 前端构建、mock API/本地 API 页面验收 |
| P1-GAP-ADMIN-1 | 超管商户管理一期 | 商户列表、新增/编辑、启停、充值入口最小闭环 | 后端 admin routers/models、前端 Super 页面 | HIGH | 超管权限、商户隔离、操作记录测试 |
| P1-GAP-KB-1 | 统一知识库训练方案 | 打通知识库训练页、9000 Agent、9100 RAG scope | `app/routers/agents.py`、9100 rag、前端智能体页 | HIGH | RAG mock 测试、知识库隔离、Prompt 注入测试 |
| P1-GAP-WECHAT-RULE-1 | 微信助手规则配置设计 | 补齐配置列表、规则类型、启停与历史记录 | 9000 配置模型/router、前端 WechatAgent | HIGH | 不触发真机发送的规则模拟测试 |

## 9. 当前验证记录

本轮文档固化阶段执行了以下安全命令：

- `git status --short`
- `git branch --show-current`
- `git log --oneline -n 30`
- 多组 `rg` / `Get-Content -Encoding UTF8` 只读检索，用于确认代码路径和能力边界。
- `python -m py_compile app/auth/newcar_client.py app/auth/context.py app/auth/dependencies.py app/routers/auth.py app/routers/compute.py app/routers/leads.py app/routers/douyin_accounts.py app/routers/douyin_ai_cs_proxy.py app/local_agent_main.py`：通过。
- `python -m pytest tests/test_auth_context.py tests/test_compute_models.py tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_usage_client.py -q`：`54 passed, 117 warnings`。
- `rg -n "�|涓|鍟|鈫|鉁|TODO|TBD" docs/ai/P1_REQUIREMENT_GAP_ANALYSIS.md docs/ai/05_PROJECT_CONTEXT.md docs/ai/08_DATA_MODEL_AUTO_WECHAT.md docs/ai/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`：未发现匹配。

上一轮探索阶段已记录：

- `python -m py_compile` 关键文件通过。
- 选定测试集合结果为 `299 passed, 3 failed, 357 warnings`。
- 3 个失败均集中在 `tests/test_p0_4a_local_agent.py` 对 `scripts/build_local_agent_exe.ps1` 的既有断言，与本轮文档固化无关。
- 未执行 `npm run build`，原因是本轮不修改前端代码，且构建可能产生无关产物。

## 10. 已知风险和阻塞项

1. 当前工作区存在其他会话未跟踪文件：`scripts/seed_dev_data.py`、`tests/test_seed_dev_data.py`。因此本轮不能直接提交，除非先得到用户确认。
2. NewCarProject 登录字段、token/cookie 规则、权限字典、过期时间未形成最终外部契约。
3. `douyin_leads` 缺 `merchant_id` / `tenant_id`，是一期多商户验收的 P0 风险。
4. 前端路由级权限隔离不足，不能只靠 `SideNav` 隐藏菜单。
5. 小高算力后端具备，但前端真实接入缺失。
6. 超管功能多数未落后端，不能按页面存在判断“已实现”。
7. 真实支付、真实自动发送、生产迁移和未验签 webhook 均不应在当前阶段贸然推进。

## 11. P0 技术方案复核

### 11.1 P1-GAP-LOGIN-1 NewCarProject 登录接入

**当前代码现状**

- `app/auth/newcar_client.py` 是 NewCarProject 认证门面，支持从环境变量读取 `NEWCAR_AUTH_ENABLED`、`NEWCAR_AUTH_MOCK_ENABLED`、`NEWCAR_AUTH_INTROSPECT_URL`、`NEWCAR_AUTH_LOGIN_URL`、`NEWCAR_AUTH_SERVICE_TOKEN`。
- `introspect_code()`、`introspect_token()`、`introspect_cookie()` 当前 mock 开启时返回 `build_mock_context()`，mock 关闭时直接返回 `NEWCAR_AUTH_UNAVAILABLE`，未调用真实 NewCarProject。
- `app/auth/context.py` 的 `RequestContext` 已预留 `user_id`、`username`、`merchant_id`、`merchant_ids`、`role_codes`、`permission_codes`、`super_admin`、`merchant_status`、`session_id`。
- `app/routers/auth.py` 的 `/auth/me` 和 `/auth/callback` 只是返回当前 `RequestContext`，仍是调试/占位性质。
- `frontend/src/pages/Login.tsx` 当前按本地账号字符串映射角色，没有提交密码到后端，也没有调用 NewCarProject `/api/login`。

**涉及文件**

- `app/auth/newcar_client.py`
- `app/auth/context.py`
- `app/auth/dependencies.py`
- `app/routers/auth.py`
- `frontend/src/pages/Login.tsx`
- `frontend/src/App.tsx`
- 后续可能新增 `frontend/src/api/auth.ts` 或复用现有 API 客户端。
- 测试：`tests/test_auth_context.py`，后续新增认证契约测试。

**数据模型变化**

- 第一阶段不建议新增本地用户表。
- `RequestContext` 字段足够承载一期登录态；如需持久化会话，应先确认 NewCarProject 是否由 token/cookie 负责，不要在 auto_wechat 里自建认证中心。

**API 变化**

- 需要确认 NewCarProject 是否提供：
  - `POST /api/login` 或跳转式登录入口。
  - token introspection 或 session 校验接口。
  - 返回字段：`user_id`、`username`、`role` / `role_codes`、`merchant_ids`、权限字典、token/cookie 规则、过期时间。
- 不要写死 NewCarProject 返回结构；建议先定义 adapter 层把外部结构转换成 `RequestContext`。

**前端变化**

- `Login.tsx` 改为调用真实登录接口或跳转 NewCarProject 登录页。
- `App.tsx` 启动时调用 `/auth/me` 恢复登录态，而不是只用内存 `user`。
- 登录后根据权限字典或默认首页策略跳转，不再统一跳 `/douyin-ai-cs`。

**测试计划**

- 单元测试：NewCarProject 返回结构转换为 `RequestContext`。
- 接口测试：缺 token 返回 401，商户禁用/套餐过期返回 403。
- 前端测试或手工验收：merchant 登录只进入商户菜单，super_admin 进入超管菜单。
- 安全测试：伪造前端 role 不应绕过后端权限。

**迁移风险**

- 认证属于 HIGH 风险。错误契约会导致全站不可登录或越权。
- 若 NewCarProject cookie 域名、SameSite、跨域策略未确认，前端登录恢复可能失败。

**回归风险**

- 当前本地开发依赖 mock 上下文。接入真实登录时必须保留开发环境 mock 开关。
- 9100 工作台和 compute 接口依赖 `RequestContext.merchant_id`，字段缺失会影响多条主链路。

**是否需要等待外部契约**

- 是。必须等待 NewCarProject 明确字段和认证方式后再开工。

**建议是否现在开工**

- 不建议直接开发真实接入。建议现在先输出并冻结 NewCarProject 登录权限契约，再做 adapter 测试。

### 11.2 P1-GAP-PERMISSION-1 权限菜单与路由隔离

**当前代码现状**

- `frontend/src/components/SideNav.tsx` 通过 `user.role !== "merchant"` 判断超管菜单，不是权限字典驱动。
- `frontend/src/App.tsx` 使用 React Router，但只注册 `/`、`/douyin-ai-cs`、`/douyin-ai-cs-test`；`/leads`、`/ai-agent`、`/compute` 等主要页面没有独立路由守卫。
- `frontend/src/pages/Index.tsx` 通过内部 `activeNav` 切换页面，路由级隔离不足。
- 后端 `app/auth/dependencies.py` 有 `require_permission()`、`require_any_permission()` 和 `require_merchant_access()`。
- 后端覆盖较好的接口：`app/routers/compute.py`、`app/routers/douyin_accounts.py`、`app/routers/douyin_ai_cs_proxy.py`、`app/routers/agents.py`。
- 后端覆盖不足或需审计的接口：`app/routers/leads.py` 取了 `RequestContext`，但因 `DouyinLead` 缺商户字段无法强过滤；`app/routers/wechat_tasks.py` 当前未看到统一 `RequestContext` 权限依赖。

**涉及文件**

- `frontend/src/App.tsx`
- `frontend/src/components/SideNav.tsx`
- `frontend/src/pages/Index.tsx`
- `frontend/src/types.ts` 或新增权限类型定义
- `app/auth/dependencies.py`
- `app/routers/*.py` 逐接口审计
- 测试：`tests/test_auth_context.py`，新增权限路由测试。

**数据模型变化**

- 本任务本身不应改数据库。
- 权限字典来自 NewCarProject，不建议在 auto_wechat 里新增权限表。

**API 变化**

- `/auth/me` 需要稳定返回 `permission_codes`、`role_codes`、`merchant_ids`、`super_admin`。
- 后端接口需统一采用可信 `RequestContext`，禁止使用前端传入 `merchant_id` 作为权限依据。

**前端变化**

- `SideNav` 改为由权限字典驱动菜单可见性。
- `App.tsx` 增加页面级路由和 `RequirePermission` 守卫。
- `Index.tsx` 内部切页应逐步收敛到路由导航，至少在一期关键页面实现 URL 级隔离。

**测试计划**

- 后端：merchant 访问超管接口返回 403；无权限访问抖音 AI 客服/compute 返回 403。
- 前端：无权限页面不可见，直接访问 URL 显示无权限或重定向。
- 安全：隐藏菜单不是权限边界，直接请求后端也必须 403。

**迁移风险**

- 权限属于 HIGH 风险。菜单收敛和路由改造可能影响所有页面入口。

**回归风险**

- 当前大量页面依赖 `activeNav`，一次性全量路由化可能引入导航回归。
- 建议先对一期验收页面做最小路由守卫，再逐步迁移。

**是否需要等待外部契约**

- 部分需要。前端和后端可以先按内部权限码设计，但最终必须等待 NewCarProject 权限字典确认。

**建议是否现在开工**

- 建议先做“权限字典契约 + 接口权限审计清单”，真实改造等待登录契约确定后开工。

### 11.3 P1-GAP-LEADS-TENANT-1 线索商户隔离

**当前代码现状**

- `app/models.py` 的 `DouyinLead` 未发现 `merchant_id` / `tenant_id` 字段。
- `DouyinWebhookEvent` 当前也缺少明确商户字段。
- `DouyinAuthorizedAccount` 有 `merchant_id`、`tenant_id`，说明企业号归属已在 9000 侧具备。
- `DouyinAccountAgentBinding` 有 `merchant_id`、`tenant_id`，且有商户+账号/商户+Agent 索引。
- `AiAgent` 有 `merchant_id` 和 `tenant_id`，能按商户隔离智能体。
- `ComputeAccount`、`ComputeTransaction` 有 `merchant_id`、`tenant_id`，算力已具备商户账本隔离。
- `app/routers/leads.py` 取 `RequestContext`，但无法在 SQL 层按商户过滤 `douyin_leads`。

**涉及文件**

- `app/models.py`
- `app/schemas.py`
- `app/integrations/douyin_webhook.py`
- `app/routers/leads.py`
- `app/services/lead_management_service.py`
- `migrations/versions/*`
- `tests/test_leads_management.py`
- webhook、douyin account、权限相关测试。

**数据模型变化**

- 设计阶段建议字段：
  - `douyin_leads.merchant_id`：可信商户 ID，后续应非空。
  - `douyin_leads.tenant_id`：预留租户/来源系统。
  - `douyin_webhook_events.merchant_id`：原始事件归属。
  - 必要索引：`idx_douyin_leads_merchant_status_created`、`idx_douyin_webhook_events_merchant_created`。
- 历史数据需要迁移归属策略：
  - 若可通过 `account_open_id` 匹配 `DouyinAuthorizedAccount.open_id`，则回填对应 `merchant_id`。
  - 无法确定归属的数据标记为 `legacy_unknown` 或进入人工归属清单。
  - 不建议默认全部归属 `dev-merchant`，除非明确仅用于本地库。

**API 变化**

- `/leads` 列表、详情、分配、重分配必须按 `RequestContext.merchant_id` 过滤。
- webhook 入库必须确定 `merchant_id`，来源可以是：
  - 根据 `account_open_id` 查 `DouyinAuthorizedAccount`。
  - 根据 NewCarProject/上游回调携带商户标识，但必须验签或可信映射。
  - 开发环境允许 mock fallback，但生产不得默默写入无商户线索。

**前端变化**

- 商户端无需传 `merchant_id`。
- 超管视角如要跨商户查看，必须使用 super_admin 权限和明确商户筛选。
- 列表筛选可增加商户维度，但仅限超管。

**测试计划**

- 迁移 dry-run：旧库新增字段不破坏现有数据。
- webhook 入库：已授权企业号事件正确写入对应商户。
- 多商户隔离：merchant-a 看不到 merchant-b 线索。
- 越权：直接请求 `/leads/{id}` 不能访问其他商户线索。
- 历史未知归属：不进入普通商户列表或按设计进入人工处理。

**迁移风险**

- HIGH。涉及核心线索表和历史数据，必须先做设计、备份、dry-run、回滚方案。
- webhook 入库无法识别商户时，生产事件可能被拒绝或进入隔离区，需要产品确认。

**回归风险**

- 线索列表、同步、分配、报表、微信任务创建、回复检测都依赖 `lead_id`。
- 若迁移后过滤过严，旧演示数据可能从前端消失。

**是否需要等待外部契约**

- 部分需要。需要确认 webhook 事件中企业号/商户标识字段，以及 NewCarProject 商户 ID 映射。

**建议是否现在开工**

- 不建议直接写 migration。建议先做数据归属设计文档和迁移演练脚本方案，确认后再实施。

### 11.4 P1-GAP-COMPUTE-FE-1 小高算力前端接入

**当前代码现状**

- 后端 `app/routers/compute.py` 已提供：
  - 商户侧 `GET /compute/summary`
  - 商户侧 `GET /compute/transactions`
  - 商户侧 `GET /compute/packages`
  - 商户侧 `POST /compute/recharge-orders`
  - 管理员侧 `GET/POST/PUT /admin/compute/packages`
  - 管理员侧 `POST /admin/merchants/{merchant_id}/compute/recharge`
  - 管理员侧 `POST /admin/merchants/{merchant_id}/compute/grant-package`
  - 内部 `POST /internal/compute/usage`
- `app/services/compute_service.py` 明确一期不做真实支付、不做余额不足拦截，充值订单是 mock，不到账不改余额。
- `frontend/src/pages/ComputeCenter.tsx` 显示“小高算力真实接口暂未接入”。
- `frontend/src/pages/SuperComputeConfig.tsx` 显示“算力套餐配置真实接口暂未接入”。
- 测试覆盖较完整：`tests/test_compute_models.py`、`tests/test_compute_service.py`、`tests/test_compute_router.py`、`tests/test_compute_usage_client.py`。

**涉及文件**

- `frontend/src/api/types.ts`
- 新增或修改 `frontend/src/api/compute.ts`
- `frontend/src/pages/ComputeCenter.tsx`
- `frontend/src/pages/SuperComputeConfig.tsx`
- 可能涉及 `frontend/src/pages/Index.tsx` 菜单入口
- 不需要改后端，除非前端接入发现响应契约缺字段。

**数据模型变化**

- 无。此任务应只接前端。

**API 变化**

- 原则上无后端 API 变化。
- 如需统一前端响应类型，只在前端类型层适配当前 `success/data/message`。

**前端变化**

- 商户端 `/compute`：
  - 展示余额、今日/昨日/累计消耗。
  - 展示 Token 明细分页。
  - 展示启用套餐。
  - 充值弹窗调用 `POST /compute/recharge-orders`，明确标注 mock 订单和非真实支付。
- 超管端：
  - 套餐列表、创建、编辑、启停。
  - 商户充值/发放套餐入口如依赖商户列表，应先用已有商户页面契约或暂缓。

**测试计划**

- 前端构建：`npm run build`。
- API mock 测试：summary、transactions、packages、recharge-orders 响应渲染。
- 手工验收：
  - merchant 可看到余额和流水。
  - merchant 创建充值订单后余额不变化，显示 mock 待支付。
  - super_admin 可管理套餐。
  - merchant 访问 admin 页面不可见或无权限。

**迁移风险**

- LOW 到 MEDIUM。无数据库变化，后端已有测试。
- 风险主要来自前端权限和超管商户选择依赖。

**回归风险**

- 若 `ComputeCenter` 接入后 API 认证失败，页面会从占位变成错误态，需要做空态和错误态。
- `npm run build` 可能暴露现有前端旧问题，需要与本任务区分。

**是否需要等待外部契约**

- 商户端不需要等待外部契约，可基于现有后端低风险开工。
- 超管端商户充值/发放如果需要商户列表，需等待或复用商户管理契约。

**建议是否现在开工**

- 建议作为低风险优先开发任务开工，先做商户端 `/compute`，再做超管套餐配置；真实支付继续不做。
