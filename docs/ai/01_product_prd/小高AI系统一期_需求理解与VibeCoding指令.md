# 小高AI系统（一期）— 需求理解与 VibeCoding 指令

> **本文档用途**：这是给 VibeCoding / AI 编码助手的项目上下文指令。读完本文档即可理解项目定位、一期任务范围、架构约束与红线，可直接开始工作。
>
> **生效日期**：2026-07-09
> **性质**：一期需求已冻结，本文档为权威理解。当本文档与 CLAUDE.md 旧约束冲突时，**以本文档为准**（见第 8 章「已推翻的旧约束」）。
>
> **2026-07-09 修订**：删除此前误加的「2.7 AI小高剪辑」章节。核对主需求原文（`docs/PRD/需求文档-小高AI系统一期（对外）.md`）确认：**2.7 实为「小高算力」、无 2.8、全文无任何剪辑字样**。AI 剪辑是**独立需求 `project_info/Project_02_一键剪辑/`**（走 ASR+Agent 流水线），不属于本项目一期；douyinAPI 的 AIGC `video_mixcut` 是历史/demo 沉淀，不属任何一期需求。一键过审属独立需求 `project_info/project_01_巨量广告/`，亦不在一期主需求范围。

---

## 0. 阅读对象与使用方式

- **谁读**：所有参与 auto_wechat 一期开发的 AI 编码助手（VibeCoding / Claude Code / Codex 等）。
- **怎么用**：作为系统提示或任务入口文档。开始任何任务前，先读本文档 + 项目 CLAUDE.md + `docs/ai/` 相关专题文档。
- **铁律**：语言用简体中文，代码注释用中文，commit message 用中文。

---

## 1. 项目定位（必读，一句话）

**「小高AI系统」是品牌伞**，统管多个子系统；**一期需求是 auto_wechat 项目的下一阶段产品扩展**（不是重做、不是纯前端文档）。需求**已冻结**。

### 子系统对应关系

| 品牌伞模块 | 实际归属 | 说明 |
|---|---|---|
| 抖音AI客服 | 9100 `apps/xg_douyin_ai_cs` | 独立服务，RAG/LLM |
| AI小高线索 | 9000 auto_wechat | 线索管理 |
| AI小高智能体 | 9000 auto_wechat | 智能体 CRUD |
| 抖音企业号管理 | 9000 auto_wechat | 企业号授权+绑定 |
| AI小高助手（微信代理） | 9000 + 19000 Local Agent | 微信自动化 |
| 小高算力 | 9000 auto_wechat | Token 账户/消耗/套餐 |

> ⚠️ **范围澄清**：主需求一期**不含 AI 剪辑**（无任何剪辑模块）。剪辑（auto_edit）是**独立需求 `project_info/Project_02_一键剪辑/`**（二手车营销视频一键剪辑，走 ASR+Agent 流水线），不属于本项目一期交付。`E:\work\project\douyinAPI` 的 AIGC `video_mixcut` 是历史/demo 沉淀，也不属于任何一期需求。

---

## 2. 服务架构拓扑

```
上游 NewCarProject / used-car (E:\work\project\used-car)
  ├─ 商户 / 账号 / 身份 / 登录 / 有效期 / 启停 / 管理员账号(3.6)
  └─ 权限码发放（auto_wechat:* 系列）
        │
        ▼ (前端直调登录，auto_wechat 只消费 token)
┌─────────────────────────────────────────────┐
│ 9000 auto_wechat（主服务）                    │
│  ├─ 线索 / 智能体 / 企业号 / 算力               │
│  ├─ 违禁词 / 回访提示词 / AI回复记录 / 算力配置 │
│  └─ knowledge_training 代理 → 9100            │
└─────────────────────────────────────────────┘
        │                           │
        ▼ HTTP                      ▼ HTTP
┌──────────────────┐        ┌──────────────────┐
│ 9100 xg_douyin_  │        │ 19000 Local Agent│
│ ai_cs             │        │ 小高AI微信助手.exe│
│ RAG(Milvus)+LLM  │        │ 本机微信自动化    │
│ 抖音客服回复大脑  │        │ 127.0.0.1 only  │
└──────────────────┘        └──────────────────┘
```

**外部资源**：
- `E:\work\project\douyinAPI`：参考实现（一键过审 OAuth 骨架），**不作生产依赖**。一键过审是独立需求 `project_info/project_01_巨量广告/`，不在一期主需求范围。
- `E:\work\project\react_base_back`：前端 UI 参考（算力页 ComputeCenter.tsx）。

---

## 3. VibeCoding 铁律与红线

### 3.1 语言规范（强制）
- 对话/解释/建议：**简体中文**
- 代码注释：**中文**
- Commit Message：**中文**
- 禁止大段未翻译英文术语

### 3.2 工作流（强制）
理解需求 → 阅读项目 → 建立上下文 → 分析影响面 → 输出方案 → 获得确认 → 实现 → 测试 → 总结。**禁止跳过阅读直接编码**。

### 3.3 高风险区（必须先做风险分析，禁止直接改）
Database Migration / Authentication / RBAC / 环境变量 / Docker / Nginx / File Storage / Background Worker / 部署脚本 / CI-CD。

### 3.4 自动发送门禁（一期已放开，见第 8 章）
一期**抖音侧 + 微信侧都放开自动发送**。但放开 ≠ 无脑发，必须配套：
- 违禁词过滤（命中替换安全词后再发）
- 人工接管降级
- 发送频率上限
- 失败回写

### 3.5 仍有效的安全约束（未推翻，必须遵守）
- 不读取微信数据库 / 不 DLL 注入 / 不微信协议逆向
- 优先 UI Automation + OCR
- Local Agent 只监听 `127.0.0.1:19000`，不监听 `0.0.0.0`
- 前端不得持有 internal token，不得直连 9100 / Milvus

### 3.6 Ponytail 原则（lazy senior dev）
最小可用 diff、复用现有工具、不引入不必要抽象/依赖、Deletion over Addition。非平凡逻辑留一个可运行的自检。

---

## 4. 权限与角色体系

### 4.1 三角色
| 角色 | 位置 | 说明 |
|---|---|---|
| merchant 商户 | auto_wechat 消费 | 1 商户 = 1 账号 |
| super_admin 超管 | auto_wechat 消费 | 权限码含 `admin` 即超管 |
| admin 管理员 | **上游 used-car** | 3.6 管理员账号管理**不在本项目** |

### 4.2 登录架构
- **前端直调 NewCarProject 登录**，auto_wechat **不实现登录接口**，只消费 token。
- 退出登录走 `POST /auth/logout`（9000 → NewCarProject `/api/external-auth/logout`）。
- token 存前端，**不支持自动刷新**；受 `NEWCAR_AUTH_ENABLED` / `NEWCAR_AUTH_MOCK_ENABLED` 控制。
- "记住账号"仅记账号字符串。

### 4.3 权限码（权威清单，见 `frontend/src/features/capabilities.ts`）
```
auto_wechat:use                         基础使用
auto_wechat:douyin_ai_cs                抖音AI客服（2.2）
auto_wechat:leads                       线索（2.3）
auto_wechat:agent                       智能体(2.4) + 微信助手(2.6) 共用
auto_wechat:compute                     算力（2.7）
auto_wechat:ai_edit                     ⚠️预留码，一期不交付（剪辑属独立 Project_02）
auto_wechat:admin:autoreply             自动回复管理
auto_wechat:admin:ai_reply_records      AI回复记录（3.4）
auto_wechat:admin:compute_config        算力配置（3.5）
auto_wechat:admin:accounts              账号（3.6，上游）
auto_wechat:admin:forbidden_words       违禁词（3.2）
auto_wechat:admin:return_visit_prompts  回访提示词（3.3）
```

### 4.4 权限矩阵双层
- 1.2 矩阵 = 商户类型**默认上限**（功能全集）
- 3.1.2「功能授权」= 每商户**实际授权**（可在上限内裁剪，**在上游管理**）

### 4.5 默认跳转
- merchant → 优先抖音AI客服，无该授权则跳第一个可用功能
- super_admin → AI 回复记录（3.4）

---

## 5. 模块全景（一期状态）

| 模块 | 状态 | 归属 | 核心一期动作 |
|---|---|---|---|
| 2.1 登录 | ✅委托 | 前端→上游 | 无 |
| 2.2 抖音客服 | ⚠️改造 | 9100 | 放开自动发送 + 移除 reply_suggestion |
| 2.3 线索 | ✅已有 | 9000 | 修已留资展示(extracted_phone) |
| 2.4 智能体 | ✅已有 | 9000 | 无（模型已全） |
| 2.5 企业号 | ✅已有 | 9000 | 补列表展示字段 |
| 2.6 微信助手 | ⚠️改造 | 9000+19000 | 放开自动发送+规则勘误+SalesStaff改造 |
| 2.7 算力 | ✅后端已实现 | 9000 | FE-1+支付mock+3套餐seed+上浮比例 |
| 3.1 商户管理 | ⛔上游 | used-car | 仅充值/发放套餐跨调 |
| 3.2 违禁词 | 🆕全新 | 9000 | 词库→违禁词→安全词，替换后仍发 |
| 3.3 回访提示词 | 🆕全新 | 9000 | 微信→抖音回访闭环 |
| 3.4 AI回复记录 | ⚠️改造 | 9000 | 展示实发+加is_effective/model |
| 3.5 算力配置 | ✅已实现 | 9000 | +上浮比例新表(按6能力) |
| 3.6 管理员账号 | ⛔上游 | used-car | 无 |
| 4 知识库训练 | ✅已实现 | 9000代理9100 | 无（已跳过） |

---

## 6. 各模块详细规格

### 2.1 登录（无本期工作）
前端直调上游；记住账号字符串；密码显隐切换；按权限码识别角色跳转。

### 2.2 抖音AI小高客服（9100，改造）
- **放开 AI 自动发送私信**（推翻 auto_send=false）。
- **移除 reply_suggestion 调试功能**（前端不显示"AI回复建议"）。
- AI 回复**唯一触发路径** = 企业号绑定智能体 + 打开自动回复开关（即 AI 托管模式）。
- 托管模式：AI托管(蓝色)/人工接管(黄色)。
- 消息标签（需人工/高意向/已留资/待回访）= **规则触发**。
- 客户字段（车型/年份/预算/城市）= **LLM 提取**。
- 在线状态 = 抖音不返回，用**最近消息时间**近似。
- 线索评分 = 基于完整度（留资意向+互动次数+车型匹配度）。
- 工具栏（表情/图片/视频/文件）一期全做。
- 模块**保留在 9100 独立服务**。

### 2.3 AI小高线索（9000，小改）
- 状态机映射层已存在：`STATUS_LABELS`（`app/services/lead_management_service.py:32`）
  - pending=新线索 / assigned=跟进中 / replied=已留资 / timeout=已失效 / closed=已成交
- **"已留资"权威判定 = `extracted_phone` 非空**（非 status）。
- ⚠️ **实施必修**：展示层"已留资"也要基于 `extracted_phone`，否则与 STATUS_LABELS 的 replied→已留资 冲突误展示。
- 高意向 = 评分 ≥ 阈值。
- 销售响应率 = 已分配中销售微信已响应比例。
- 跟进记录时间线主数据源 = `LeadFollowupRecord`（record_type: assign/reassign/reply_check/notification/feedback/manual_note）。
- 对话跟进按钮 → 跳 2.2 工作台对应会话，用 open_id 关联。
- 重新分配 = 手动选销售（弹窗），`reassign_count` 已有。
- 联系电话未留资显示"未留资"占位。
- 溯源信息字段现有但抖音不返回。

### 2.4 AI小高智能体（9000，已完备）
- 模型 `AiAgent` 已全：name / prompt / knowledge_base_text / avatar_seed / status / merchant_id。
- 知识库 = ①"知识参考提示词"（文本框 knowledge_base_text）+ ②勾选"参考小高知识库"（叠加系统级 RAG）。
- 头像：本地生成假随机（avatar_seed）。
- 数量：商户无限制。
- 删除：**硬删除**；已被企业号绑定的智能体**必须先解绑**才能删。
- 创建智能体与绑定企业号解耦。

### 2.5 抖音企业号管理（9000，补字段）
- 授权 OAuth 已有（`DouyinAuthorizedAccount` + `DouyinOAuthState`），跳转授权页方式。
- 绑定智能体已有（`DouyinAccountAgentBinding`，`is_default` 一期一企业号一智能体）。
- Key = 抖音 `client_key`，**不展示**给商户。
- 授权状态展示：`bind_status=1`→已授权，其余→未授权。
- **取消授权 = 仅本地标记 `bind_status=3`**（抖音无 unbind API）。
- 换绑智能体 = 直接覆盖。
- 数量无限制，按 `merchant_id` 隔离。
- 删除 = 软删，已绑定/有会话数据可直接删；⚠️ `DouyinAccountAgentBinding` 需级联处理。
- 企业号标签：一期不做。
- **抖音号数字 ID：抖音实际不返回**，前端该字段隐藏或占位"-"。

### 2.6 AI小高助手 / 微信代理（9000+19000，改造）
- **微信侧自动发送一期放开**（推翻 sent=false）。
- ⚠️ **需求规则勘误**：原文 4 类规则错误。**实际 4 类 = 线索分配 / 销售盈亏表 / 客户溯源表（原文"湖源"为笔误）/ 总表**。
- "配置" = **复用 `SalesStaff` 改造**（不新建表），加 4 个规则布尔字段。
- 不做"立即下载"，只检测微信是否已打开，调 19000。
- 客户端状态（未启动/未登录/已登录）由 19000 探测上报，已登录靠 UIA/OCR 兜底（后续方案设计）。
- **"启动微信测试"验收口径（完整闭环）**：针对每个微信配置 → 自动打开微信窗口 → 搜索联系人 → 进入聊天框 → 输入对应"线索模板" → 自动发送。
- 统计（已分配/进行中/已成交/已失效）对应状态机 assigned/closed/timeout。
- 历史记录对应 `WechatTask` 表。
- 前端重构对齐现有 WechatAgent 页。

### 2.7 小高算力（9000，前端+小补）
- 后端已实现：`compute.py` + `apps.compute.services`。
- **支付一期保持 mock**（react_base_back 无真实支付 SDK）；FE-1 可参考 `react_base_back/src/pages/ComputeCenter.tsx`。
- **初始化写入 3 个套餐 seed**：基础99元/100000、标准299元/350000、专业699元/900000。
- 付款码：mock 用空白图片占位，真实为微信/支付宝二维码。
- 上线阻塞 3 项**已全部解决**：权限码已登记 / COMPUTE_INTERNAL_TOKEN 已配置 / super_admin 口径对齐。
- ⚠️ **计费规则·Token 上浮比例**：展示 = 实际字符计量 × 上浮比例（实际1000 + 33% → 显示1330）。需新增"上浮比例"管理员配置。
- USAGE-1：所有 AI 操作上报消耗。

### 3.1 商户管理（⛔ 不在本项目，在上游 used-car）
- 商户 CRUD / 功能授权 / 类型 / 有效期 / 门店 / 启停**全在上游**。
- 需求 3.1.2"功能授权"描述有误（在上游）。
- 唯一跨服务对接：上游超管"充值/发放套餐"调 auto_wechat `admin recharge/grant`。

### 3.2 违禁词管理（9000，全新）
- 权限码 `auto_wechat:admin:forbidden_words` 已定义，前端占位、后端未实现（used-car 有部分代码可参考）。
- 3 类词库**预置固定**：二手车销售基础违禁词 / 金融方案合规词库 / 车况承诺风险词。管理员只维护词列表。
- **全局级**，所有商户共享。
- 词库结构：**违禁词 → 安全词，每词单独映射**。
- **过滤机制：AI 回复 → 命中违禁词 → 替换为安全词 → 仍自动发送**（不拦截、不降级）。
- 每词一行存储（便于按词查询/统计命中）。
- 命中记录 + 前端展示 + 回写抖音客服自动发送回复。

### 3.3 回访提示词管理（9000，全新）
- 权限码 `auto_wechat:admin:return_visit_prompts` 已定义，前端导航/后端待实现。
- 3 类提示词**预置固定**：留资转化回访 / 金融方案回访 / 沉默客户唤醒。全局级。场景化模板。
- **消费链路（微信→抖音回访闭环，一期需跑通简化版）**：
  ```
  2.6微信助手(线索分配规则)
    → 系统分配线索给销售
    → 销售微信回复（如"手机号不对"/"客户不通过"）
    → ReplyCheck 检测到回复
    → LLM 分析回复语义：判断是否需抖音回访（代码关键字列表兜底）
    → 命中场景（留资转化/金融方案/沉默唤醒）
    → 2.2 抖音 LLM 基于对应回访提示词模板生成私信文案
    → 自动发送抖音私信给客户（如"再给一下手机号"）
  ```
- ⚠️ **ReplyCheck 需扩展**：不仅检测是否回复，还要分析回复语义判断是否需回访。
- 一期 = LLM 分析 + 关键字兜底（简化版）；二期 = LangChain/LangGraph Agent。

### 3.4 AI回复记录（9000，改造）
- 权限码已定义，`AiReplyDecisionLog` + `ai_reply_decision_logs.py` 已有。
- **"AI回复" = 实发内容**（`DouyinPrivateMessageSend.content`），非建议 `reply_text`。
- 数据源 = `DouyinPrivateMessageSend` JOIN `AiReplyDecisionLog`（靠 `decision_log_id` 关联）。
- **AiReplyDecisionLog 新增**：`is_effective` + `effectiveness_reason`（冗余预留）+ `model`（对齐 `ComputeTransaction.model`）。
- 标记有效 = **超管手动**，非自动判定。
- 超管全量 + 可按商户筛选。

### 3.5 算力配置（9000，已实现+小补）
- 套餐 CRUD 已实现（`ComputePackage` + admin 接口）。
- **上浮比例新配置表**：按**功能模块粒度（capability_gateway 的 6 能力：douyin-cs/leads/agents/wechat-assistant/compute/knowledge）**，全局统一（不分商户）。
- 前端套餐配置页待 FE-1。

### 3.6 管理员账号（⛔ 上游 used-car，不在本项目）

### 4.x 统一知识库训练（已实现，跳过）
9000 代理调 9100，scope 固定 `xiaogao_system`/`xiaogao_base`，IP 白名单 + internal token 鉴权。

---

## 7. 数据模型变更总清单（Database Migration 高风险）

> 涉及迁移，**必须先做风险分析 + 迁移脚本 + dry-run + 回滚方案**，禁止直接改。

| 表 | 变更 | 来源模块 |
|---|---|---|
| `sales_staff` | 加 4 个规则布尔字段（线索分配/盈亏表/溯源表/总表） | 2.6 |
| `ai_reply_decision_logs` | 加 `is_effective` / `effectiveness_reason` / `model` | 3.4 |
| `forbidden_word_libraries`（新） | 3 类预置词库（名称/启停） | 3.2 |
| `forbidden_words`（新） | 违禁词→安全词映射，每词一行， belongs to library | 3.2 |
| `return_visit_prompts`（新） | 3 类预置提示词（名称/模板/启停/场景类型） | 3.3 |
| `compute_markup_ratios`（新） | 按 6 功能模块的上浮比例 | 3.5 |
| `compute_packages` | 写入 3 个 seed（不强制，可初始化脚本） | 2.7/3.5 |
| `douyin_authorized_accounts` | 删除时 `douyin_account_agent_bindings` 级联处理 | 2.5 |

---

## 8. 已推翻的 CLAUDE.md 旧约束（⚠️ VibeCoding 必读）

> **以下约束已在一期作废。若 VibeCoding 读到 CLAUDE.md 旧描述，以本章为准。**

| 旧约束（已作废） | 一期新决策 |
|---|---|
| "AI 回复 auto_send 恒为 false" | **抖音侧放开自动发送** |
| "reply_decision_service 全路径 auto_send=False" | 同上 |
| `DouyinPrivateMessageSend.auto_send` "P1-H must always be 0" | 可置 1（放开后） |
| `AiReplyDecisionLog.final_auto_send` "必须为 0" | 可置 1 |
| "9100 reply_suggestion 回复建议功能" | **一期移除**（调试残留） |
| "业务自动派单发送仍禁止，sent 必须为 false" | **微信侧放开自动发送** |
| "不允许把 sent 置为 true" | 可置 true |
| "不允许发送 Enter / 不允许业务自动派单发送" | 允许（完整闭环） |

**配套必须**（放开自动发送后强制）：违禁词过滤、人工接管降级、频率上限、失败回写、紧急停止。

---

## 9. 实施路线图（建议顺序）

### 阶段 0 · 门禁放开方案（最高优先，最高风险）
1. 抖音侧自动发送门禁放开方案（含配套兜底设计）
2. 微信侧自动发送门禁放开方案（含 SalesStaff 规则字段迁移）
3. 违禁词库（3.2）作为自动发送的安全前置

### 阶段 1 · 数据模型迁移（高风险）
按第 7 章清单，逐表迁移 + dry-run + 测试。

### 阶段 2 · 全新模块
- 3.2 违禁词管理（前后端）
- 3.3 回访提示词 + 微信→抖音回访闭环

### 阶段 3 · 改造模块
- 2.2 移除 reply_suggestion + 放开自动发送
- 2.6 微信助手重构 + 规则字段
- 3.4 AI回复记录（实发展示 + is_effective/model）

### 阶段 4 · 前端 + 埋点
- FE-1 算力页（参考 ComputeCenter.tsx）
- 3.2/3.3 超管页接入
- USAGE-1 所有 AI 操作上报算力（字符 × 上浮比例）

---

## 10. 开放点最终结论（已全部确认）

| 问题 | 最终结论 |
|---|---|
| 2.6「客户湖源表」 | 是「客户**溯源**表」笔误 |
| 3.2 违禁词→安全词 | **每词单独映射** |
| 3.3 微信→抖音回访闭环 | **一期需跑通简化版**（LLM + 关键字兜底） |
| 3.5 上浮比例粒度 | 按**功能模块（6 能力）** |
| 2.5 抖音号数字 ID | **抖音不返回**，前端隐藏/占位 |

---

## 11. 参考资源

| 资源 | 路径/链接 | 用途 |
|---|---|---|
| 项目入口规范 | `CLAUDE.md` | 项目铁律（注意第 8 章推翻项） |
| 权限码全貌 | `frontend/src/features/capabilities.ts` | 功能授权映射 |
| 能力网关 | `app/routers/capability_gateway.py` | 6 能力健康检查 |
| 算力服务 | `app/routers/compute.py` + `apps.compute.services` | 余额/消耗/套餐 |
| 过审 OAuth 参考 | `E:\work\project\douyinAPI\app.py` | 一键过审 OAuth 骨架（独立 project_01，非一期） |
| 算力页 UI | `E:\work\project\react_base_back\src\pages\ComputeCenter.tsx` | FE-1 参考 |
| 项目记忆 | `C:\Users\A\.claude\projects\e--work-project-auto-wechat\memory\xg-phase1-*.md` | 9 条一期决策详情 |

---

## 12. 给 VibeCoding 的最终指令

1. **开始任何任务前**：读本文档 + CLAUDE.md（注意第 8 章推翻项）+ 对应模块的 `docs/ai/` 专题。
2. **涉及自动发送**：必须确认配套兜底已设计（违禁词/降级/频率/失败回写）。
3. **涉及数据库**：走迁移流程（脚本 + dry-run + 回滚），不直接改 models 生效。
4. **涉及外部 API**（抖音/上游）：先确认授权、签名、限流。
5. **不确定时**：先探索代码确认现状，再出方案，不臆测。
6. **语言**：全程简体中文，注释中文，commit 中文。
