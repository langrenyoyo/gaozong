# P0 抖音自动回复前置 LLM 门禁实施计划

> **给代理开发者：** 按任务逐项执行；本计划只在 Owner 已批准 Decision Delta 后使用，不得扩大范围。

**目标：** 在 9000 现有 evaluate_pre_llm_gates 入口增加 prohibited_auto_reply 的消息级阻断，并让前端持久展示当前消息未自动回复，同时保证下一条普通消息恢复正常 AI 链路。

**架构：** 复用 forbidden_word_libraries/forbidden_words 和 AiAutoReplyRun 现有持久化；门禁顺序固定为最新客户消息检查、禁止自动回复检查、既有人工接管/限频、LLM。命中只结束当前消息，不改变会话状态。API 仅增加向后兼容的 auto_reply_status、auto_reply_reason 字段。

**技术栈：** Python、FastAPI、SQLAlchemy、PostgreSQL/现有测试数据库、React、TypeScript、pytest。

---

## 1. 范围与前置审批

- Decision Delta：docs/architecture/remediation/P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1-DECISION-DELTA-v1.0.md
- Owner 已批准 seed：黑户、老赖、我黑了、征信花了。
- 明确不加入：贷款、金融、分期、征信（单词）。
- 不改 Schema，不新增 migration。
- 不改 webhook、outbox、9100、Prompt、RAG、LLM 调用层或真实发送链。
- G3 新增：M01-PRE-LLM-BLOCK-1、M01-PRE-LLM-RECOVERY-1。

实施前必须执行：

- [ ] git status
- [ ] git branch --show-current
- [ ] git rev-parse HEAD
- [ ] 重新定位 evaluate_pre_llm_gates、AiAutoReplyRun 查询 API 和前端运行记录类型；不依赖旧行号。

## 2. 文件责任映射

| 文件 | 责任 | 计划动作 |
|---|---|---|
| app/services/douyin_autoreply_gate_service.py | 前置门禁唯一入口 | 修改门禁顺序和 prohibited_auto_reply 判断 |
| app/services/forbidden_word_service.py | 现有词库读取/命中能力 | 优先复用；仅在接口不支持按 library_key 读取时做最小内部扩展 |
| migrations/versions/0047_forbidden_word_seed.sql | 历史 seed 证据 | 只读参考，禁止修改，禁止新增 migration |
| app/schemas.py | 运行记录 API 响应模型 | 增加可选 auto_reply_status、auto_reply_reason |
| app/services/ai_auto_reply_run_query_service.py | 运行记录列表/详情组装 | 从已有 status、block_reason、gate_results_json 组装新字段 |
| app/routers/ai_auto_reply_runs.py | 当前商户运行记录 API | 保持权限/租户边界，返回 additive 字段 |
| frontend/src/api/types.ts | 自动回复运行记录类型 | 增加可选字段 |
| frontend/src/features/douyin-cs/riskFlagLabels.ts | 阻断原因展示映射 | 增加 prohibited_auto_reply 文案映射 |
| frontend/src/features/douyin-cs/pages/DouyinAutoReplyRunsPage.tsx | 运行记录列表/详情 | message-level 文案、刷新后展示 |
| frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx | 工作台最新运行记录展示 | 仅当该页面消费同一运行记录时补充 message-level 状态 |
| tests/test_ai_auto_reply_dry_run.py | 9000 自动回复门禁回归 | 增加阻断、恢复、状态不污染用例 |
| tests/test_forbidden_word_service.py | 词库读取和 scope 回归 | 增加新库隔离和排除词用例 |
| tests/test_forbidden_word_seed_migration.py | seed 结构回归 | 扩展为 seed 可重复、四词存在、排除词不进入新库 |
| tests/test_ai_auto_reply_runs_api.py 或当前对应 API 测试文件 | additive API | 验证新字段和商户隔离 |
| frontend 对应测试目录 | 前端展示 | 验证固定文案和刷新后仍从 API 恢复 |
| docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml | G3 SSOT | 仅在实现和测试通过后更新 M01 两项证据 |

如果当前仓库没有列出的某个测试文件，使用现有同职责测试文件，不新建 competing framework。

## 3. Task 1：冻结并验证 seed 交付路径

### 目标

将四个词条放入已有词库体系，且不修改历史 migration。

### 步骤

- [ ] 步骤 1：定位现有可执行 seed 入口

  读取现有 seed 脚本、部署 seed 命令和数据库运维文档，确认如何在已完成 0047 的数据库中幂等插入新库和词条。

- [ ] 步骤 2：验证历史 migration 不可作为新增交付

  migrations/versions/0047_forbidden_word_seed.sql 和对应 PostgreSQL migration 只作为历史事实参考；不得追加内容，因为已应用数据库不会重新执行历史 migration。

- [ ] 步骤 3：若已有 seed 入口，新增幂等 seed

  seed 逻辑必须等价于：

      library_key = prohibited_auto_reply
      words = 黑户、老赖、我黑了、征信花了
      excluded = 贷款、金融、分期、征信

  使用现有库唯一约束和已有 seed 风格，不能新增字段、表或 migration。

- [ ] 步骤 4：若没有已批准 seed 入口则停止

  不自行新建运维脚本或修改历史 migration；提交 CHANGES_REQUIRED，说明“无 migration 约束下缺少可执行 seed 交付路径”，等待 Owner 指定现有入口或批准一次性运维 seed。

- [ ] 步骤 5：运行 seed 回归

  运行当前 seed 测试文件，确认四词只属于 prohibited_auto_reply，finance_compliance 仍保留原词条，排除词不进入新库。

## 4. Task 2：为 pre-LLM gate 写失败测试

Files:

- Test: tests/test_ai_auto_reply_dry_run.py
- Test: tests/test_forbidden_word_service.py

- [ ] 步骤 1：新增禁止消息用例

  构造客户消息“我征信花了”，为商户加载 prohibited_auto_reply，断言：

      run.status == blocked
      run.block_reason == prohibited_auto_reply
      gate_results.pre_llm.prohibited_auto_reply.blocked is True
      gate_results.pre_llm.prohibited_auto_reply.matched_words == [征信花了]
      run.llm_used is False
      send_event_count == 0

- [ ] 步骤 2：新增普通金融词用例

  构造“贷款怎么做”或“有没有分期”，只命中 finance_compliance，不命中 prohibited_auto_reply；断言 pre-LLM 不因新库阻断，后续 AI 链路按既有 gate 继续。

- [ ] 步骤 3：新增连续消息恢复用例

  先处理“我征信花了”，再处理“有没有电车”；断言第一条 LLM=0/SEND=0，第二条重新通过 prohibited_auto_reply 检查并进入现有 AI 链路，第二条不继承第一条 block_reason。

- [ ] 步骤 4：新增多轮不污染用例

  使用 prohibited -> normal -> prohibited -> normal，逐条断言 gate 结果独立，conversation mode、manual_takeover_until 和 managed mode 不因 prohibited 命中改变。

- [ ] 步骤 5：新增租户隔离用例

  商户 A 的新库命中不得影响商户 B；查询 A 的运行记录不得返回 B；禁止使用请求中伪造 merchant_id 绕过当前商户过滤。

- [ ] 步骤 6：先运行失败测试

  运行：

      python -m pytest tests/test_ai_auto_reply_dry_run.py tests/test_forbidden_word_service.py -k "prohibited_auto_reply or finance_compliance or recovery or tenant" -v

  预期：新增断言在实现前失败；记录失败原因，不修改测试绕过失败。

## 5. Task 3：实现最小 pre-LLM gate

Files:

- Modify: app/services/douyin_autoreply_gate_service.py
- Reuse: app/services/forbidden_word_service.py

- [ ] 步骤 1：保持唯一入口

  所有新规则只进入 evaluate_pre_llm_gates；不在 webhook、outbox、9100 或 send chain 添加平行判断。

- [ ] 步骤 2：调整当前客户消息检查顺序

  在 gate 内先完成 latest_message customer check；非客户消息直接沿用现有 skip/block 语义，不执行 prohibited_auto_reply。

- [ ] 步骤 3：加入新库查询

  对已确认的客户消息调用现有词库服务，限定 library_key=prohibited_auto_reply 和当前可信 merchant/scope；不得读取 finance_compliance 作为替代。

- [ ] 步骤 4：命中立即返回消息级阻断

  返回值必须表达：

      status = blocked
      reason = prohibited_auto_reply
      gate_results.pre_llm.prohibited_auto_reply.blocked = true
      gate_results.pre_llm.prohibited_auto_reply.matched_words = safe summaries

  该分支不得调用人工接管、限频、LLM、post-LLM 或发送。

- [ ] 步骤 5：未命中继续既有 gate

  按 Decision Delta 继续人工接管、限频和后续链路；不修改 conversation state，不写 manual takeover。

- [ ] 步骤 6：运行 Task 2 测试

  预期新增 pre-LLM 用例通过，既有人工接管和限频用例不回归。

## 6. Task 4：补充 additive API 字段

Files:

- Modify: app/schemas.py
- Modify: app/services/ai_auto_reply_run_query_service.py
- Modify: app/routers/ai_auto_reply_runs.py（仅当响应组装需要）
- Test: tests/test_ai_auto_reply_runs_api.py 或当前对应测试文件

- [ ] 步骤 1：扩展 Pydantic 响应

  在 AiAutoReplyRunListItem 增加：

      auto_reply_status: str | None = None
      auto_reply_reason: str | None = None

  旧字段保持原样，字段可选，旧客户端可忽略。

- [ ] 步骤 2：组装字段

  对 message-level prohibited 命中返回：

      auto_reply_status = not_replied
      auto_reply_reason = prohibited_auto_reply

  普通运行不伪造新原因；可返回 null 或由既有 status/block_reason 派生的兼容值，保持旧语义。

- [ ] 步骤 3：保持查询隔离

  列表和详情继续使用可信 RequestContext merchant_id；不得接受查询参数 merchant_id 作为过滤依据，不得跨商户查询 gate_results_json。

- [ ] 步骤 4：验证 API

  断言新增字段存在且旧字段仍存在；A 商户不能读取 B 的状态；旧响应消费者不因新增可选字段失败。

## 7. Task 5：前端 message-level 展示

Files:

- Modify: frontend/src/api/types.ts
- Modify: frontend/src/features/douyin-cs/riskFlagLabels.ts
- Modify: frontend/src/features/douyin-cs/pages/DouyinAutoReplyRunsPage.tsx
- Modify: frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx（仅确认同一运行记录需要展示时）
- Test: 当前前端测试目录中对应运行记录/门禁展示测试

- [ ] 步骤 1：增加类型

  在 AiAutoReplyRunListItem 及 detail 类型中增加可选 auto_reply_status、auto_reply_reason。

- [ ] 步骤 2：增加文案映射

  prohibited_auto_reply 只映射为“命中禁止自动回复规则”；不得映射为“会话人工接管”或“AI 自动回复已暂停”。

- [ ] 步骤 3：渲染固定文案

  当 auto_reply_status=not_replied 且 auto_reply_reason=prohibited_auto_reply 时渲染：

      标题：本条消息未自动回复
      说明：命中禁止自动回复规则，后续消息不受影响。

  文案挂在当前运行记录/当前消息卡片，不放在会话顶部状态或账号设置。

- [ ] 步骤 4：验证刷新

  先由 API 返回字段渲染，再刷新页面重新请求列表/详情，断言相同 message-level 文案仍存在；禁止使用仅存于 React state 的临时标记。

- [ ] 步骤 5：前端回归

  运行项目现有前端类型检查和相关测试；确认人工接管、普通 blocked reason 和历史运行记录文案不回归。

## 8. Task 6：LLM/SEND 负向验证与 G3

Files:

- Test: tests/test_ai_auto_reply_dry_run.py
- Test: 现有发送事件/real_send gate 测试文件
- Modify: docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml（仅验收通过后）

- [ ] 步骤 1：验证 LLM=0

  使用可观测的 9100 调用 mock/spy，命中四个 seed 词条时断言 9100 调用计数为 0；不能只根据 run.status 推断。

- [ ] 步骤 2：验证 SEND=0

  使用 send event 和 real_send_candidate 记录断言命中时两者均为 0；不得把“没有前端按钮”作为发送未发生的证据。

- [ ] 步骤 3：验证恢复

  高风险消息后发送普通问题，断言第二条出现正常 9100 调用，并且其发送决策只由既有 post-LLM/send gate 决定。

- [ ] 步骤 4：登记 G3

  在 G3 SSOT 中新增 M01-PRE-LLM-BLOCK-1、M01-PRE-LLM-RECOVERY-1；每项包含输入、LLM=0/SEND=0 或恢复证据、租户范围和运行 HEAD。

- [ ] 步骤 5：确认 G4

  本计划不更新 G4；若实现需要修改 webhook、outbox、9100、send chain 或跨模块合同，立即停止并提交新的 G4 影响评估。

## 9. Task 7：完整回归与文档影响检查

- [ ] 步骤 1：运行后端聚焦测试

      python -m pytest tests/test_ai_auto_reply_dry_run.py tests/test_forbidden_word_service.py tests/test_forbidden_word_seed_migration.py tests/test_ai_auto_reply_runs_api.py -v

  若 API 测试文件名称不同，使用当前仓库对应文件，不创建第二套测试框架。

- [ ] 步骤 2：运行发送与租户隔离回归

  运行现有自动回复发送、real_send gate、权限和跨商户测试集合，确认 SEND=0 负例和正常发送路径均通过。

- [ ] 步骤 3：运行前端检查

  运行项目现有 TypeScript/build/test 命令，确认 additive 字段、固定文案和刷新路径通过。

- [ ] 步骤 4：执行文档影响检查

  检查 M01 CURRENT_FLOW、G3 矩阵和相关测试说明；只更新因本任务事实过期的文档，不修改治理规则文件。

- [ ] 步骤 5：输出验收报告

  报告必须逐项列出：seed、LLM=0、SEND=0、金融词恢复、连续消息恢复、多轮不污染、租户隔离、API additive、前端刷新、G3 两项。

## 10. 完成门与禁止事项

完成门：

- [ ] Owner seed 四词和排除词均验证。
- [ ] prohibited 命中只影响当前消息。
- [ ] LLM=0、SEND=0 有独立运行证据。
- [ ] 下一条普通消息恢复 AI。
- [ ] finance_compliance 与新库隔离。
- [ ] auto_reply_status、auto_reply_reason additive contract 通过。
- [ ] 前端固定文案 message-level 且刷新后可见。
- [ ] M01-PRE-LLM-BLOCK-1、M01-PRE-LLM-RECOVERY-1 G3 证据通过。
- [ ] Schema/migration/webhook/outbox/9100/send chain 无越界改动。

禁止：

- 禁止修改历史 0047 migration；
- 新增 migration 或 Schema；
- 硬编码关键词；
- 把命中变成会话暂停、人工接管、AI 关闭或 managed mode；
- 修改 webhook、outbox、9100、Prompt、RAG、LLM、真实发送链；
- 自行扩展 seed 词条；
- 自动提交、推送、部署。

## 11. 计划状态

    PLAN = P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1
    OWNER_CONFIRMATION = COMPLETE
    STATUS = IMPLEMENTATION_PLAN_READY_FOR_OWNER_REVIEW
    CODE_CHANGE = NOT_EXECUTED
    DB_SCHEMA_CHANGE = NOT_EXECUTED
    MIGRATION_CHANGE = NOT_EXECUTED
    PRODUCTION_CHANGE = NOT_EXECUTED
    COMMIT = NO
    PUSH = NO
    DEPLOYMENT = NO
    STOP = YES
