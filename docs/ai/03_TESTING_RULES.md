# AI Coding Testing Rules

> 本文档是 AI Coding Agent 的测试规范。
>
> 本规范用于约束 AI 在完成代码修改后如何设计测试、执行验证、说明风险。
>
> 本规范优先级低于：
>
> ```text
> 01_READING_RULES.md
> 05_PROJECT_CONTEXT.md
> 02_EXECUTION_RULES.md
> ```
>
> 高于输出规范。

------

# 1. 核心原则

测试的目标不是证明“代码能跑”。

测试的目标是证明：

```text
需求被正确实现

旧功能没有被破坏

边界情况被覆盖

异常路径可控

修改可以被验证

问题可以被回归
```

任何代码修改后，都必须说明如何验证。

------

# 2. 测试分层

AI 必须根据任务类型选择合适的测试层级。

常见测试层级：

```text
Unit Test
Integration Test
E2E Test
Regression Test
Manual Verification
Stability Test
Security Test
Performance Test
```

不是所有任务都需要全部测试。

但任何任务都必须至少有一种验证方式。

------

# 3. Unit Test 规则

适用于：

```text
纯函数

工具函数

规则判断

状态转换

Parser

数据转换

权限判断

边界逻辑
```

Unit Test 应覆盖：

```text
正常输入

异常输入

空值

边界值

非法状态

历史 Bug 场景
```

要求：

```text
测试必须稳定

不依赖外部服务

不依赖真实网络

不依赖真实第三方 API

可以重复执行
```

------

# 4. Integration Test 规则

适用于：

```text
多个模块协作

Service 调用 Repository

API 调用 Service

任务编排

数据库读写

缓存交互

外部服务 Mock
```

Integration Test 应验证：

```text
模块之间能正确协作

数据流转正确

事务边界正确

异常可以被正确处理

依赖服务失败时行为符合预期
```

默认原则：

```text
第三方 API 默认 Mock

LLM 默认 Mock

邮件默认 Mock

支付默认 Mock

外部网络默认 Mock
```

------

# 5. E2E Test 规则

适用于：

```text
核心业务链路

用户关键路径

提交 / 审批 / 支付 / 登录 / 上传 / 通知 等完整流程
```

E2E Test 应验证：

```text
用户入口

前后端请求

数据写入

结果展示

权限限制

异常提示
```

E2E 不应过多。

只覆盖核心路径和高风险路径。

------

# 6. Regression Test 规则

凡是修复 Bug，必须补充回归测试或回归验证步骤。

必须说明：

```text
原 Bug 如何复现？

修复后如何证明不再发生？

是否会影响相邻功能？

是否需要新增测试用例？
```

禁止只修 Bug 不说明回归验证。

------

# 7. Manual Verification 规则

如果当前项目没有自动化测试，或者任务不适合自动化测试，必须提供手工验证步骤。

手工验证必须具体。

禁止：

```text
手动测试一下

页面看一下

接口测一下
```

必须写成：

```text
1. 打开哪个页面 / 调用哪个接口
2. 使用什么输入
3. 预期看到什么结果
4. 失败时会出现什么现象
5. 如何确认旧功能未受影响
```

------

# 8. LLM / AI 功能测试规则

涉及以下内容时适用：

```text
Prompt

Agent

RAG

Tool Calling

Embedding

Retriever

LLM Output Parser

结构化输出
```

默认规则：

```text
日常测试默认 Mock LLM

Prompt 变更才需要真实模型稳定性测试

LLM 输出必须校验结构

Parser 必须测试异常输出

必须覆盖 Prompt Injection 或越权输入
```

至少验证：

```text
正常输出

格式错误输出

空输出

超时

模型拒答

注入攻击

Fallback 逻辑
```

------

# 9. 外部服务测试规则

涉及：

```text
邮件

短信

支付

对象存储

搜索服务

第三方 API

消息队列

Webhook
```

默认规则：

```text
日常测试使用 Mock 或测试环境

禁止默认调用生产环境

禁止默认发送真实通知

禁止默认扣费或创建真实订单

禁止默认写入真实外部资源
```

必须验证：

```text
成功路径

失败路径

超时

重试

幂等性

异常日志
```

------

# 10. 数据库测试规则

涉及数据库时，必须验证：

```text
新增数据是否正确

历史数据是否兼容

唯一约束是否生效

外键关系是否正确

事务失败是否回滚

软删除是否受影响

Migration 是否可升级和回滚
```

涉及数据库结构变更时，必须提供：

```text
升级验证

回滚验证

历史数据兼容验证
```

------

# 11. 权限测试规则

涉及权限时，必须覆盖：

```text
有权限用户

无权限用户

不同角色用户

越权访问

前端隐藏按钮绕过

后端接口直接调用
```

权限测试必须以后端结果为准。

前端隐藏按钮不能作为权限验证依据。

------

# 12. 状态流转测试规则

涉及状态变化时，必须覆盖：

```text
合法状态流转

非法状态流转

重复提交

并发提交

失败回滚

历史状态兼容
```

禁止只测最终结果，不测状态过程。

------

# 13. 安全测试规则

涉及以下内容时必须增加安全验证：

```text
认证

权限

文件上传

下载

路径访问

SQL

命令执行

HTML 渲染

外部链接

Webhook

Prompt
```

至少考虑：

```text
越权

注入

路径穿越

XSS

CSRF

SSRF

敏感信息泄露

Prompt Injection
```

------

# 14. 性能与稳定性测试规则

以下情况需要考虑性能验证：

```text
循环查询

批量导入

大文件处理

高频接口

异步任务

搜索

LLM 调用

复杂计算
```

至少说明：

```text
是否存在 N+1 查询

是否可能超时

是否需要分页

是否需要限流

是否需要异步处理

是否需要缓存
```

------

# 15. 测试矩阵输出要求

进入实现或完成实现后，AI 必须输出测试矩阵。

格式：

```text
# 测试矩阵

| 场景 | 类型 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 正常路径 | Unit / Integration / E2E | xxx | xxx | xxx |
| 异常路径 | Unit / Integration | xxx | xxx | xxx |
| 权限路径 | Integration / Manual | xxx | xxx | xxx |
```

------

# 16. 测试执行说明

AI 必须说明：

```text
已执行哪些测试

未执行哪些测试

为什么未执行

需要用户手动执行什么

测试失败时如何排查
```

禁止：

```text
测试通过
```

但没有说明测试内容。

------

# 17. 最终原则

没有验证方案的代码，不算完成。

没有回归验证的 Bug 修复，不算完成。

没有权限验证的权限修改，不算完成。

没有回滚验证的数据库修改，不算完成。

测试不是最后一步。

测试是修改方案的一部分。
------

# 18. BUG 修复回归测试原则

凡是修复 Bug，必须：

```text
补充回归测试，或明确说明无法自动测试的原因
```

必须说明：

```text
1. 原 Bug 如何复现？
   - 输入条件
   - 前置状态
   - 触发步骤
   - 预期失败现象

2. 修复后如何证明不再发生？
   - 测试用例
   - 验证步骤
   - 预期成功结果

3. 是否会影响相邻功能？
   - 受影响的模块
   - 受影响的调用链
   - 受影响的状态流转

4. 是否需要新增测试用例？
   - 边界测试
   - 异常路径测试
   - 回归测试
```

禁止：

```text
只修 Bug 不写回归测试（除非明确说明无法自动测试）

只验证修复点，不验证相邻功能

只测正常路径，不测异常路径
```

当无法自动测试时，必须说明：

```text
1. 为什么无法自动测试
2. 手工验证步骤
3. 预期结果
4. 如何确认旧功能未受影响
```

------

# 19. 高风险逻辑日志验证原则

涉及以下高风险场景的代码修改，必须验证日志输出：

```text
微信 UI 自动化
OCR 识别
联系人验证
前台焦点切换
粘贴/发送门禁
任务状态流转
线索同步/派发
exe 启动和运行时
```

验证要求：

```text
1. 修改后必须确认日志能正确输出
2. 日志内容必须包含 stage、输入摘要、判断结果
3. 失败时日志必须包含 failure_stage 和拒绝原因
4. 敏感信息必须脱敏
5. 异常路径必须有日志覆盖
```

测试矩阵中必须包含：

```text
| 场景 | 日志验证 |
|------|----------|
| 正常路径 | 日志输出 stage + 关键参数 + 成功结果 |
| 失败路径 | 日志输出 stage + 输入摘要 + failure_stage + 原因 |
| 异常路径 | 日志输出异常类型 + 关键状态 |
| 安全门禁 | 日志输出门禁检查结果 + 拒绝原因 |
```

------

# 20. 微信自动化回归基线（P1-END-1 起）

涉及微信自动化 / Local Agent 的改动，至少执行以下回归基线：

### 后端 / Local Agent

```bash
python -m py_compile app/local_agent_main.py
python -m pytest tests/test_p0_main_5b_poll_and_execute.py -v
python -m pytest tests/test_p1_auto_1c_poll_and_detect.py -v
python -m pytest tests/test_p1_auto_1d_fix4_safe_json.py -v
```

### 前端

```bash
npm run build
```

### 真机验收必检项（检测闭环基线）

注：第 3、9 项是**检测闭环**的只读基线（检测链路永远 sent=false / pasted=false）；发送侧一期已放开硬门禁，真实发送按 gate 口径另行验收（违禁词替换、人工接管、限频、失败回写、幂等、紧急停止）。

| # | 检查项 | 预期 |
|---|--------|------|
| 1 | 新 lead 创建成功 | lead_id 有值 |
| 2 | notify_sales task 创建并按 task_id 执行 | task_id 指定，非队列头部 |
| 3 | paste_only 成功 | pasted=true, sent=false |
| 4 | detect_reply task 自动创建 | reply_check_id 有值 |
| 5 | detect_reply 按 task_id 执行 | task_id 指定 |
| 6 | 销售回复识别 | detected_status=replied, matched_reply 有值 |
| 7 | notification 状态更新 | send_status=销售已回复 |
| 8 | check 状态更新 | check_status=replied |
| 9 | sent=false / pasted=false（检测链路） | action 中均为 false |
| 10 | search-debug 不再 500 | 返回 200 + 合法 JSON |
| 11 | 不出现 task_type_not_notify_sales | 任务类型正确 |
| 12 | 不被旧 pending 队列阻塞 | task_id 机制生效 |

------

# 21. 全量回归注意事项

以下是反复出现的环境性失败，跑全量回归前必须知道：

```text
1. 全量 pytest 必须忽略 PyInstaller 产物目录，否则 collection 被污染：
   python -m pytest --ignore=dist --ignore=dist_backup_20260616_130831

2. 本地 .env 若 NEWCAR_AUTH_ENABLED=true，不 override auth 的测试会批量 401；
   回归诊断先设 NEWCAR_AUTH_ENABLED=false 或用 worktree 对照。

3. proxy env（.env.lan.local 被 app.config 加载）会使 proxy+llm 组合测试
   大面积失败（pre-existing）；含 proxy 的回归失败先隔离验证。

4. 存在 pre-existing 失败基线；判断回归用 git stash / worktree 对比
   "零新增失败" 放行，不要求历史全绿。

5. dev 库 schema 漂移：data/auto_wechat.db 可能缺新字段，
   用全局 engine 的测试会 OperationalError；用内存库的同类测试不受影响。
```
