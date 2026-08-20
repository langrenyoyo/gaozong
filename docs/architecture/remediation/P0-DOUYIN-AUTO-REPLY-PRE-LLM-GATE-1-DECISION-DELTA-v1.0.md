# P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1

## Decision Delta v1.0

> 状态：APPROVED_PENDING_IMPLEMENTATION_PLAN
> 当前阶段：Reality Check 已完成；本文件只冻结业务规则和实施边界
> 禁止：直接编码、Schema 迁移、生产修改、部署、提交、推送

## 0. Reality Check 基线

当前代码已确认：

- app/services/douyin_autoreply_gate_service.py 存在唯一前置入口 evaluate_pre_llm_gates；
- 现有前置门禁包含最新消息方向、人工接管和限频检查；
- forbidden_word_libraries 与 forbidden_words 已存在，当前词库为固定分类体系；
- AiAutoReplyRun.gate_results_json 已保存门禁结果，前端已有自动回复运行记录和 pre_llm 展示；
- 9000 自动回复链路已经把前置门禁作为 LLM 前的阻断点；
- 本任务不是修改 webhook、outbox、9100 或真实发送链。

以上事实只作为本 Decision Delta 的实现定位依据。若实施前实际 HEAD 与此不同，必须重新提交 Reality Check，不得按旧行号机械实现。

## 1. 业务目标确认

### 1.1 规则性质

禁止自动回复规则属于：

    MESSAGE LEVEL BLOCK

它不是：

- conversation pause；
- AI 关闭；
- 人工接管；
- managed mode 切换。

一次命中只影响当前客户消息。不得创建或修改会话级暂停状态，不得把命中结果写成 manual_takeover，不得改变账号或会话的 AI 模式。

### 1.2 当前消息语义

“当前消息”指本次准备进入自动回复链路的客户消息。阻断记录必须能关联该次自动回复运行记录或等价的 message-level 事实，以支持刷新后展示和审计。

## 2. 自动回复状态契约

冻结：

    BLOCK_SCOPE = CURRENT_MESSAGE_ONLY
    CONVERSATION_STATE_CHANGE = NO
    AUTO_HANDOFF = NO
    NEXT_SAFE_MESSAGE_RECOVERY = YES

### 2.1 连续消息行为

    Message A:
      命中 prohibited_auto_reply
      -> 不调用 LLM
      -> 不发送
      -> 只记录当前消息的门禁结果
      -> 不改变 conversation mode / manual takeover / managed mode

    Message B:
      普通问题
      -> 重新执行完整 pre-LLM gate
      -> 若未命中其它已有门禁，恢复正常 AI 链路
      -> 可以调用 LLM
      -> 按既有 post-LLM 和 send gate 决定是否发送

Message A 的命中不得污染 Message B 的 gate 结果、Prompt、对话模式或发送决策。

### 2.2 与已有人工接管的边界

prohibited_auto_reply 的命中原因必须与 manual_takeover 分开记录。禁止用“请人工处理”作为该规则的业务状态或前端默认语义；人工接管只有在已有人工接管规则真实命中时才成立。

## 3. 数据模型决策

### 3.1 复用模型

复用：

- forbidden_word_libraries
- forbidden_words

新增 seed：

    library_key = "prohibited_auto_reply"

该库表达“命中后阻断当前消息且不进入 LLM”，不是词条严重程度。

### 3.2 明确禁止

- 不用 severity 代替行为分类；
- 不复用 finance_compliance；
- 不在 Python、TypeScript、Prompt、webhook 或配置代码中硬编码关键词；
- 不把 prohibited_auto_reply 词条混入普通回复替换词或 LLM 约束词列表；
- 不因一次命中创建 conversation pause 或人工接管状态。

### 3.3 Schema 与 migration

    DB_DELTA = SEED_ONLY
    SCHEMA_CHANGE = NO
    MIGRATION = NO

实施只允许增加 forbidden_word_libraries/forbidden_words 的 seed 数据和相应 seed 回归测试。不得新增字段、表、索引、migration revision 或 create_all 路径。

seed 必须：

- 通过现有库 key 唯一约束；
- 可重复执行且不重复插入；
- 绑定正确的 library_id；
- 不覆盖现有 safe_word、severity 或其他库词条；
- 明确启用状态；
- 具有租户/全局 scope 语义时复用现有库模型，不新增 scope 字段。

## 4. Gate 插入点冻结

### 4.1 唯一入口

    evaluate_pre_llm_gates

不得在 webhook、outbox、9100、send chain 或多个调用方分别实现同一规则。

### 4.2 执行顺序

固定顺序：

    latest_message customer check
      ↓
    prohibited_auto_reply check
      ↓
    人工接管 / 限频等已有 gate
      ↓
    LLM

要求：

- 最新消息不是客户消息时，不执行客户消息禁止规则；
- 当前消息确认是客户消息后，先检查 prohibited_auto_reply；
- 命中后立即返回 message-level blocked decision；
- 命中后不得执行人工接管、限频、LLM、post-LLM 或发送；
- 未命中时继续现有人工接管、限频和后续链路；
- 既有其它 gate 的语义和顺序只按本节明确调整，不顺手重构。

### 4.3 明确不修改

本任务不修改：

- webhook 接收和事件幂等；
- outbox claim/lease、worker 或发送任务；
- 9100 API、Prompt、RAG、LLM 调用层；
- 真实发送链、send gate、post-LLM gate；
- conversation mode、manual takeover 状态模型；
- 数据库 Schema 和 migration。

## 5. 前端展示契约

### 5.1 统一文案

禁止展示：

- “AI自动回复已暂停”
- “请人工处理”

采用：

    标题：本条消息未自动回复
    说明：命中禁止自动回复规则，后续消息不受影响。

展示必须是 message 级，不得渲染为会话级、账号级或 AI 模式级状态。

### 5.2 持久化与刷新

前端刷新后仍可见该条消息的阻断结果。实现优先复用现有 AiAutoReplyRun/gate_results_json 和运行记录详情；不得新增前端本地临时状态作为唯一事实。

若实施前确认现有 API 未返回该 message-level gate 结果：

- 只能提出向后兼容的最小响应字段补充；
- 先更新 API Contract 和影响评估；
- 未经 Owner 批准不得直接改 API。

### 5.3 与其它状态标签的关系

prohibited_auto_reply 不得被映射为：

- manual_takeover；
- managed_mode；
- conversation_paused；
- AI disabled。

可展示安全的内部原因标签，但用户可见主文案必须保持本节固定语义。

## 6. 验收测试要求

### 6.1 禁止词命中

输入：客户消息命中 prohibited_auto_reply。

必须断言：

    LLM = 0
    SEND = 0

同时断言：

- 记录当前消息的 blocked reason；
- 不创建或修改 conversation pause；
- 不设置 manual takeover；
- 不执行 webhook/outbox/9100 旁路动作。

### 6.2 普通金融词

输入：普通金融咨询词，不属于 prohibited_auto_reply。

必须断言：

- 继续现有 AI 回复链路；
- 不因 severity 或 finance_compliance 误阻断；
- LLM 是否调用由其它既有 gate 决定；
- 本任务不得把普通金融词扩大为禁止自动回复词。

### 6.3 高风险消息后下一条普通消息

输入：

    Message A = 命中禁止规则
    Message B = 普通问题

必须断言：

- A：LLM=0、SEND=0；
- B：重新执行 pre-LLM gate；
- B 在没有其它阻断时恢复 AI；
- B 不继承 A 的 blocked reason、manual takeover 或 pause 状态。

### 6.4 多轮消息污染

至少覆盖：

    prohibited -> normal -> prohibited -> normal

必须断言每条消息独立判断，禁止把前一条结果写入后续消息状态。

### 6.5 租户隔离

至少覆盖：

- 商户 A 的禁止词 seed/命中结果不影响商户 B；
- 非可信 merchant_id 不能查询或使用其它商户的运行记录；
- global 词库只按既有全局 scope 读取，不复制成商户可篡改配置；
- 一个商户命中不改变另一个商户的会话模式或 AI 状态。

### 6.6 Seed 回归

必须验证：

- library_key="prohibited_auto_reply" 存在且唯一；
- seed 可重复执行；
- 既有库 key 和词条数量不被覆盖；
- severity 不承担阻断行为；
- finance_compliance 仍保持原语义。

## 7. 影响评估

### 7.1 BUSINESS_CODE_DELTA

    YES

原因：

- 在 evaluate_pre_llm_gates 增加当前消息级禁止规则判断；
- 固定 latest customer check -> prohibited check -> existing gates 的顺序；
- 命中时不调用 LLM、不发送；
- 未命中时保持已有链路；
- 禁止结果与 manual_takeover、conversation state 分离。

### 7.2 DB_DELTA

    SEED_ONLY

只新增 prohibited_auto_reply 库及其词条 seed。Schema、表、字段、索引、migration 均不变。

### 7.3 API_DELTA

    NO_CONTRACT_DELTA_EXPECTED

优先复用现有自动回复运行记录和 gate_results_json 展示 message-level 结果。若 Reality Check 的实际响应未暴露该字段，必须先提交向后兼容的 API Contract Delta；本 Decision Delta 不授权隐式 API 修改。

### 7.4 FRONTEND_DELTA

    YES

只修改门禁结果的 message-level 展示和刷新后的历史渲染，固定使用：

    本条消息未自动回复
    命中禁止自动回复规则，后续消息不受影响。

不得新增会话暂停、AI 关闭或人工接管控件。

### 7.5 G3_DELTA

    REQUIRED

原因：

- M01 自动回复关键链新增一个前置业务节点；
- G3 验证矩阵需要增加“命中禁止规则不进 LLM/不发送”和“下一条普通消息恢复”的链路证据；
- 需要新增 message-level persistence、连续消息和租户隔离验证项。

G3 只更新受影响的 M01 验证事实，不重开无关模块验证。

### 7.6 G4_DELTA

    NO

原因：

- 规则落在 M01 既有 evaluate_pre_llm_gates 内；
- 不改变 M02/M04/M06/M07 Owner；
- 不修改 webhook、outbox、9100、send chain 或跨模块 Contract；
- 前端只消费既有运行记录展示。

若实施中发现需要改 API Contract、outbox 或发送链，必须停止并重新提交 G4/范围变更，不得沿用本结论。

## 8. 实施边界

### 允许

- evaluate_pre_llm_gates 内的最小门禁逻辑；
- 复用现有 forbidden word service/library/word 查询；
- 增加 seed 数据；
- 保存或补充当前消息级 gate result（仅使用已有持久化能力）；
- 前端 message-level 文案和历史展示；
- 对应 unit、integration、regression、G3 验收测试；
- 必要技术文档更新。

### 禁止

- 修改数据库 Schema；
- 新增 migration；
- 修改 webhook、outbox、9100、Prompt、RAG、LLM 层；
- 修改真实发送链；
- 把命中结果变成 conversation pause、AI 关闭、人工接管或 managed mode；
- 用 severity 或 finance_compliance 代替新库；
- 硬编码关键词；
- 新增第三方服务、队列、缓存或复杂规则引擎；
- 通过随机或概率策略处理命中；
- 扩大为全局 AI 开关或商户级暂停能力。

## 9. Implementation Plan 编写条件

只有在以下条件确认后，才能编写实施计划：

1. Owner 确认 prohibited_auto_reply 的 seed 词条清单；
2. Owner 确认现有 gate result 是否足以支持刷新后的 message-level 展示；
3. Owner 确认普通金融词不进入该库；
4. Verification Authority 确认 LLM=0、SEND=0 的可观测断言位置；
5. G3 验证矩阵接受新增 M01 链路与连续消息用例；
6. API Contract 评估确认无需响应字段变化，或先批准最小 additive contract delta。

未满足以上条件，不得直接编码。

## 10. 最终决策

    DECISION = APPROVED
    STATUS = APPROVED_PENDING_IMPLEMENTATION_PLAN
    IMPLEMENTATION_PLAN = ALLOWED_ONLY_AFTER_SECTION_9_CONFIRMATION
    CODE_CHANGE = 0
    DB_SCHEMA_CHANGE = 0
    MIGRATION_CHANGE = 0
    WEBHOOK_CHANGE = 0
    OUTBOX_CHANGE = 0
    S9100_CHANGE = 0
    SEND_CHAIN_CHANGE = 0
    PRODUCTION_CHANGE = 0
    COMMIT = NO
    PUSH = NO

本 Decision Delta 仅冻结规则、边界和验收要求。禁止直接编码。

STOP
