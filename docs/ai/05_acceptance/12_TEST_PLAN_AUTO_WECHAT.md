# auto_wechat / 小高AI微信助手 第一版产品化测试验收计划

版本：P0-TESTPLAN-1  
日期：2026-06-15  
范围：本轮只输出测试验收计划，不写业务代码、不修改测试代码、不修改数据库模型、不新增接口、不改配置默认值、不启动服务、不执行迁移、不执行真机微信自动化。

------

## 0. 文档依据与验收口径

本文基于以下已冻结或已完成文档：

1. `docs/ai/01_product_prd/06_PRD_AUTO_WECHAT.md`
2. `docs/ai/02_architecture/07_ARCHITECTURE_AUTO_WECHAT.md`
3. `docs/ai/03_data_and_migration/08_DATA_MODEL_AUTO_WECHAT.md`
4. `docs/ai/04_interface_contracts/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`
5. `docs/ai/04_interface_contracts/10_WEBHOOK_AUTH_MIGRATION.md`
6. `docs/ai/12_legacy_research/11_CODE_PLAN_AUTO_WECHAT.md`
7. `docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md`

验收口径：

1. 第一版正式产品化验收以 `POST /webhook/douyin`、生产强制验签、原始事件入库、联系方式提取、有效线索生成、销售分配、Local Agent 任务、回复检测、状态流转、导出为主线。
2. `POST /integrations/douyin/webhook` 是兼容路径，必须与正式路径行为一致，但不作为对外正式验收入口。
3. `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 仅允许开发 / 联调兼容，不作为正式验收通过口径。
4. Local Agent 真机验收必须保持 P1-END-1 安全边界：`sent=false`、检测只读、不粘贴、不发送、不按 Enter、9000 不直接操作微信。
5. 第一版不接入 LLM，不保存截图，不把 douyinAPI 作为正式生产运行时依赖。

------

## 1. 测试范围总览

| 模块 | 测试范围 | 主要类型 | 优先级 |
|---|---|---|---|
| Webhook 验签 | 正确签名、错签、缺头、过期、生产强制验签、开发免验签 | 安全 / 接口 | P0 |
| Webhook 路由兼容 | `/webhook/douyin` 与 `/integrations/douyin/webhook` 行为一致 | 接口 / 回归 | P0 |
| 原始事件入库 | 合法事件、非线索事件、invalid、重复事件、验签失败不入业务表 | 集成 / 数据库 | P0 |
| 私信 content 二次解析 | 字符串 JSON、非法 JSON、空 content、非文本消息 | 单元 / 集成 | P0 |
| 手机号 / 微信号提取 | 手机号、关键词微信号、多联系方式、反例 | 单元 | P0 |
| 有效线索生成 | 有联系方式进入有效线索，无联系方式不参与分配 | 集成 | P0 |
| invalid 原始事件 | 展示、导出、不分配、不建任务、不回调 | 集成 / 前端 | P1 |
| 幂等与重复事件 | `event_key`、`server_message_id`、`open_id + account_open_id` | 集成 / 并发 | P0 |
| 状态流转 | 13 个内部状态、4 个对外状态映射 | 单元 / 集成 | P0 |
| 销售管理 | 新增、修改、停用、唯一约束 | 接口 / 前端 | P1 |
| 销售导入 | 模板、部分成功、错误行号、重复覆盖 | 接口 / 文件 | P1 |
| 自动分配 | 空销售、轮流分配、避免连续过多 | 集成 | P0 |
| 非工作时间 | `delay_assign` 与到工作时间后继续分配 | 单元 / 集成 | P1 |
| 超时重分配 | 默认 30 分钟、最多 5 次、排除原销售 | 集成 / 定时任务 | P1 |
| 人工处理 | 重新分配、补录回复、关闭、审计 | 接口 / 前端 | P1 |
| Local Agent 任务拉取 | 指定 `task_id`、pending fallback、互斥、`agent_busy` | 回归 / 真机 | P0 |
| Local Agent 发送通知 | `notify_sales/send_notice`、paste_only、失败回写 | 回归 / 真机 | P0 |
| Local Agent 回复检测 | `detect_reply`、只读、关键词命中、失败回写 | 回归 / 真机 | P0 |
| 任务失败回写 | `failure_stage`、`failure_reason`、raw_result、幂等 | 集成 / 回归 | P0 |
| 日志与脱敏 | request_id、trace_id、敏感信息脱敏、错误日志 | 安全 / 日志 | P1 |
| 导出 | Excel、时间范围、invalid、导出不改状态 | 接口 / 文件 | P1 |
| 数据迁移 / 旧数据兼容 | SQLite 备份、迁移幂等、旧状态映射、旧表可读 | 迁移 / 回滚 | P1 |
| 前端接口回归 | 列表、详情、分页、筛选、状态展示、导出 | 前端 / E2E | P1 |
| 旧路径兼容 | 旧 webhook、旧 reports/checks、旧 douyinAPI 同步开关 | 回归 | P2 |
| 性能和并发基础验证 | 200 QPS 设计检查、2000 线索 / 天、任务抢占 | 性能 / 稳定性 | P2 |

------

## 2. Webhook 验签测试

### 2.1 验签开启

| # | 场景 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 1 | 正确签名 | 原始 body + 正确 timestamp + 正确 Authorization | HTTP 200，返回 `code=0` | 接口测试 |
| 2 | 错误签名 | Authorization 任意改动 | HTTP 401 | 接口测试 |
| 3 | 缺少 Authorization | 不传 Authorization | HTTP 401 | 接口测试 |
| 4 | 缺少 timestamp | 不传 `X-Auth-Timestamp` | HTTP 401 | 接口测试 |
| 5 | timestamp 非数字 | `X-Auth-Timestamp=abc` | HTTP 401 | 接口测试 |
| 6 | timestamp 过期 | 超过 `DY_ALLOWED_DRIFT_SECONDS` | HTTP 401 | 接口测试 |
| 7 | timestamp 未来超窗 | 未来时间超过允许窗口 | HTTP 401 | 接口测试 |
| 8 | body 空格变化 | 签名用 body A，请求发 body B | HTTP 401 | 接口测试 |
| 9 | SECRET_KEY 缺失 | 生产环境缺少密钥 | 启动失败或请求拒绝 | 配置 / 接口 |
| 10 | Authorization 日志脱敏 | 发起请求后检查日志 | 不出现完整 Authorization | 日志检查 |
| 11 | SECRET_KEY 日志脱敏 | 发起成功和失败请求 | 不出现 SECRET_KEY | 日志检查 |

验收注意：

1. 签名必须使用 `request.body()` 原始 bytes。
2. 禁止用 JSON 解析后重新序列化的 body 验签。
3. 验签失败不得进入业务原始事件表。

### 2.2 验签关闭

| # | 场景 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 1 | 开发环境关闭验签 | `APP_ENV=development` 且 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` | 合法 payload 可接收 | 接口测试 |
| 2 | staging 关闭验签 | staging 临时关闭 | 必须有文档说明、时间窗口和日志 | 人工审查 |
| 3 | 生产关闭验签 | `APP_ENV=production` 且关闭验签 | 启动失败或请求拒绝 | 配置 / 接口 |
| 4 | 关闭状态日志 | 免验签请求 | 日志明确 `webhook_auth_required=false` | 日志检查 |
| 5 | 正式验收排除免验签 | 验收报告 | 不把免验签作为通过条件 | 人工审查 |

### 2.3 douyinAPI 对照测试

| # | 场景 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 1 | 同 body 签名一致 | 使用 douyinAPI `test_webhook.py` 同 body / timestamp / secret | auto_wechat 签名一致 | 单元测试 |
| 2 | 同 timestamp 过期逻辑 | 使用同一过期时间戳 | auto_wechat 返回 401 | 接口测试 |
| 3 | 不迁移缺头放行 | 缺少签名头 | auto_wechat 生产验签开启时 401 | 接口测试 |
| 4 | 不依赖 douyinAPI | 停止 douyinAPI 服务 | auto_wechat webhook 验签仍可本地验证 | 架构审查 |

------

## 3. Webhook 路由兼容测试

| # | 场景 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 1 | 正式路径接收 | `POST /webhook/douyin` | HTTP 200 | 接口测试 |
| 2 | 兼容路径接收 | `POST /integrations/douyin/webhook` | HTTP 200 | 接口测试 |
| 3 | 共用验签 | 两路径同 body / 签名 | 结果一致 | 接口测试 |
| 4 | 共用事件处理 | 两路径同事件 | 幂等行为一致 | 集成测试 |
| 5 | 生产不能绕过验签 | 兼容路径缺签名 | HTTP 401 | 安全测试 |
| 6 | 日志记录入口 | 分别请求两路径 | 日志包含 `source_path` | 日志检查 |
| 7 | 正式验收路径 | 验收报告 | 以 `/webhook/douyin` 为准 | 人工审查 |

------

## 4. 原始事件入库测试

| # | 场景 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 1 | 合法 JSON | 验签通过 + JSON 合法 | 写入 `douyin_webhook_events` | 集成测试 |
| 2 | 语义承接 | 查询事件域 | `douyin_webhook_events` 语义承接 `lead_source_events` | 数据检查 |
| 3 | 非线索事件 | `im_send_msg` | 只写原始事件，不建线索 | 集成测试 |
| 4 | 无效线索 | `im_receive_msg` 无联系方式 | 写原始事件，标记 invalid / not_matched | 集成测试 |
| 5 | 重复事件 | 相同 `event_key` | 不重复建线索；记录幂等命中 | 集成测试 |
| 6 | 验签失败 | 错签请求 | 不写业务原始事件表 | 安全测试 |
| 7 | JSON 非法 | body 非法 JSON | 返回 400，记录失败日志 | 接口 / 日志 |
| 8 | 不保存 SECRET_KEY | 查询事件表和日志 | 无 SECRET_KEY | 安全检查 |
| 9 | Authorization 安全保存 | 查询事件表和日志 | 仅脱敏或 hash | 安全检查 |
| 10 | raw_payload 完整 | 合法事件 | 保存完整原始业务 payload | 数据检查 |

------

## 5. 私信 content 解析测试

| # | 场景 | 输入 / 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| 1 | content 字符串 JSON | `content="{...}"` | 二次解析成功 | 单元测试 |
| 2 | content 非法 JSON | `content="{bad"` | 不生成有效线索 | 单元 / 集成 |
| 3 | content 为空 | `content=""` | 不生成有效线索 | 单元 / 集成 |
| 4 | 文本消息 | `message_type=text` | 尝试提取联系方式 | 单元 / 集成 |
| 5 | 非文本消息 | image / card 等 | 只记原始事件 | 集成测试 |
| 6 | 会话 ID | 含 `conversation_short_id` | 正确提取保存 | 单元测试 |
| 7 | 消息 ID | 含 `server_message_id` | 正确提取保存 | 单元测试 |
| 8 | create_time | 含 `create_time` | 正确提取保存 | 单元测试 |
| 9 | 用户资料 | 含昵称、头像 | 正确提取保存 | 单元测试 |
| 10 | 解析失败日志 | content 解析异常 | 日志含失败原因，不含敏感明文 | 日志检查 |

------

## 6. 联系方式提取测试

### 6.1 手机号

| # | 输入文本 | 预期结果 |
|---|---|---|
| 1 | `我的手机号是13812345678` | 提取 `13812345678` |
| 2 | `电话 13812345678` | 提取 `13812345678` |
| 3 | `13812345678` | 提取 `13812345678` |
| 4 | `138 1234 5678` | 按实现方案明确是否归一化 |
| 5 | `1234567890` | 不提取 |
| 6 | `99999999999` | 不提取或低置信，按实现方案说明 |

### 6.2 微信号

| # | 输入文本 | 预期结果 |
|---|---|---|
| 1 | `微信 abc123` | 提取 `abc123` |
| 2 | `wx abc123` | 提取 `abc123` |
| 3 | `vx abc123` | 提取 `abc123` |
| 4 | `v abc123` | 提取 `abc123`，并重点验证误识别 |
| 5 | `加我 abc123` | 提取 `abc123` |
| 6 | `加我微信 abc123` | 提取 `abc123` |
| 7 | `订单 abc123` | 无关键词时是否提取，按方案说明 |
| 8 | `微信 ab` | 过短不提取 |
| 9 | `微信 张三123` | 含中文不提取或按规则处理 |

### 6.3 多联系方式

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 同一文本多个手机号 | 全部保存，主字段取第一个 |
| 2 | 同一文本多个微信号 | 全部保存，主字段取第一个 |
| 3 | 同时有手机号和微信号 | 两类都保存 |
| 4 | `all_extracted_contacts` | 保存完整结果 |
| 5 | 匹配成功 | `contact_extract_status=matched` |
| 6 | 未匹配 | `contact_extract_status=not_matched` |
| 7 | 解析失败 | `contact_extract_status=parse_failed` |

------

## 7. 有效线索生成测试

| # | 场景 | 预期结果 | 验证方式 |
|---|---|---|---|
| 1 | `im_receive_msg` + 手机号 | 创建 / 更新有效线索 | 集成测试 |
| 2 | `im_receive_msg` + 微信号 | 创建 / 更新有效线索 | 集成测试 |
| 3 | `im_receive_msg` 无联系方式 | 不进入有效分配 | 集成测试 |
| 4 | `im_send_msg` | 不进入有效线索 | 集成测试 |
| 5 | 非线索事件 | 不进入有效线索 | 集成测试 |
| 6 | 顶层 phone / wechat | 第一版不依赖 | 单元 / 集成 |
| 7 | `retain_consult_card` | 第一版不依赖 | 单元 / 集成 |
| 8 | LLM | 第一版不调用 | 代码审查 |
| 9 | 来源字段 | `phone` / `wechat` 来源为文本提取结果 | 数据检查 |
| 10 | 原始文本 | `raw_message_text` 保存完整文本 | 数据检查 |
| 11 | 同用户同账号 | 同 `open_id + account_open_id` 更新原线索 | 集成测试 |
| 12 | 同用户不同会话 | 视为同一用户线索更新 | 集成测试 |

------

## 8. invalid 原始事件测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 无联系方式事件 | 只进入 `douyin_webhook_events` |
| 2 | invalid 与线索表 | 不进入有效 `douyin_leads`，或按确认方案进入 `status=invalid` |
| 3 | 销售分配 | invalid 不参与分配 |
| 4 | 微信任务 | invalid 不创建微信通知任务 |
| 5 | 回调 | invalid 不对外回调 |
| 6 | 前端展示 | 可在列表或原始事件列表展示 |
| 7 | 导出 | 可导出 |
| 8 | 导出字段 | 包含失败原因 / 提取状态 |

------

## 9. 幂等测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 相同 `event_key` | 不重复创建事件或标记重复 |
| 2 | 相同 `server_message_id` | 不重复创建线索 |
| 3 | 相同 `customer_id + server_message_id` | 商户内幂等 |
| 4 | 相同 `open_id + account_open_id` | 更新原线索 |
| 5 | 重复事件响应 | HTTP 200 |
| 6 | 微信任务 | 不重复创建微信通知任务 |
| 7 | 幂等日志 | 日志记录命中原因 |

并发补充：

1. 高频重复请求不能绕过唯一约束。
2. 任务回写重复提交不能重复推进状态。
3. 导出重试不能改变业务状态。
4. **原子幂等（DY-CS-WEBHOOK-ATOMIC-IDEMPOTENCY-1）最终候选 `96a764e25defda5978d9c2d593e168ff411193c0` 已通过独立测试（R3-T1，A1-A14 全部验收通过，任务级结论 PASS）**：9000 与 9202 共用同一处理核心 `process_webhook_event`，跨方言原子占位 `ON CONFLICT DO NOTHING RETURNING` + 2 个 JSONB CAST，嵌套提交已消除（commit 计数器验证默认 1 次、commit=False 0 次），非预期异常整体回滚（A4 异常前断言四类数据已入事务、异常后 rollback 监视 + 新 Session 断言全部为 0）；19 个重复返回继承非空 lead_id，19 条重复审计行继承 lead_id、merchant_id、tenant_id；独立测试：专项 28 passed、三类 20 路并发各重复 10 轮共 30 passed、完整指定回归 163 passed，合计 221 passed, 0 failed；已通过普通快进推送集成至 `master@96a764e25defda5978d9c2d593e168ff411193c0`；尚未部署或发布，未验证真实 PostgreSQL、PostgreSQL MVCC 并发、生产环境和真实私信/自动回复/微信发送，未运行全仓测试。

------

## 10. 状态流转测试

必须覆盖内部状态：

```text
received
invalid
delay_assign
pending_assign
assigned
notified
waiting_reply
replied
timeout
reassigned
manual_required
failed
closed
```

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 工作时间有效线索 | 进入 `pending_assign` |
| 2 | 非工作时间有效线索 | 进入 `delay_assign` |
| 3 | 到工作时间 | `delay_assign` 进入分配流程 |
| 4 | 分配成功 | 进入 `assigned` |
| 5 | 通知成功 | 进入 `notified` 或 `waiting_reply` |
| 6 | 命中回复关键词 | 进入 `replied` |
| 7 | 超时未回复 | 进入 `timeout` |
| 8 | 触发重分配 | 进入 `reassigned` 或重新分配 |
| 9 | 失败 | 进入 `failed` 或 `manual_required` |
| 10 | 人工关闭 | 进入 `closed` |
| 11 | closed 恢复 | 第一版不允许恢复 |
| 12 | closed 回调 | 不对外回调 |

对外状态映射必须只输出：

```text
未分配
已分配
已回复
超时未回复
```

------

## 11. 销售管理与导入测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 新增销售 | 创建成功 |
| 2 | 修改销售 | 字段更新成功 |
| 3 | 停用销售 | 不参与新分配 |
| 4 | 微信昵称为空 | 校验失败 |
| 5 | 销售姓名为空 | 允许 |
| 6 | 手机号为空 | 允许 |
| 7 | 备注为空 | 允许 |
| 8 | 重复微信昵称 | 按 `customer_id + wechat_nickname` 覆盖 |
| 9 | Excel 模板下载 | 返回模板 |
| 10 | Excel 部分成功 | 成功行写入，失败行返回原因 |
| 11 | 导入失败详情 | 返回行号和原因 |
| 12 | 唯一约束 | 同客户微信昵称唯一 |
| 13 | 停用后分配 | 不再参与新分配 |
| 14 | 历史线索 | 销售停用后历史线索暂不处理 |

------

## 12. 自动分配与超时重分配测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 有销售列表 | 自动分配 |
| 2 | 销售列表为空 | 进入未分配 |
| 3 | 多销售 | 按排序轮流分配 |
| 4 | 连续分配 | 避免同一销售连续接收过多 |
| 5 | 默认超时 | 30 分钟 |
| 6 | 可配置超时 | 按客户配置生效 |
| 7 | 最大重分配 | 最多 5 次 |
| 8 | 排除原销售 | 重分配不选原销售 |
| 9 | 超过次数 | 进入人工处理或失败记录 |
| 10 | timeout 映射 | 对外“超时未回复” |
| 11 | reassigned 映射 | 对外“未分配” |

------

## 13. Local Agent 测试

### 13.1 任务互斥

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 同一 agent 同时两任务 | 只允许一个执行 |
| 2 | execute 与 detect 并发 | 互斥 |
| 3 | 忙碌拉取 | 返回 `agent_busy` |
| 4 | 重复拉取同一任务 | 不重复执行 |

### 13.2 发送任务

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 拉取发送任务 | 获取 `send_notice/notify_sales` |
| 2 | 成功通知 | 回写成功，`sent=false` 按安全门禁保持 |
| 3 | 联系人未找到 | 回写失败 |
| 4 | 微信不可用 | 回写失败 |
| 5 | 搜索框焦点未确认 | 禁止粘贴 |
| 6 | 联系人未确认 | 禁止发送 |
| 7 | 失败字段 | 有 `failure_stage` 和 `failure_reason` |
| 8 | 安全门禁 | 保持 P1-END-1 真机安全约束 |

### 13.3 检测任务

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 拉取检测任务 | 获取 `detect_reply` |
| 2 | 只读检测 | 不写输入框 |
| 3 | 粘贴 | 不允许 |
| 4 | 发送 | 不允许 |
| 5 | 命中关键词 | 回写已回复 |
| 6 | 未命中关键词 | 继续等待或保持状态 |
| 7 | 检测失败 | 回写失败原因 |
| 8 | 动作字段 | `sent=false`、`pasted=false` |

必跑回归：

```bash
python -m pytest tests/test_p0_main_5b_poll_and_execute.py -v
python -m pytest tests/test_p1_auto_1c_poll_and_detect.py -v
python -m pytest tests/test_p1_auto_1d_fix4_safe_json.py -v
```

------

## 14. 回复检测测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 配置关键词 | 保存成功 |
| 2 | 命中“收到” | 判定 replied |
| 3 | 命中“已添加微信” | 判定 replied |
| 4 | 命中“已联系” | 判定 replied |
| 5 | 未命中关键词 | 不误判 |
| 6 | 通知模板文本 | 不与销售回复误匹配 |
| 7 | 过短关键词 | 提示风险 |
| 8 | 过宽泛关键词 | 提示风险 |
| 9 | 命中后状态 | 进入 `replied` |
| 10 | 未命中状态 | 不误判已回复 |

------

## 15. 人工处理测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 人工重新分配 | 进入未分配或分配流程 |
| 2 | 人工补录回复 | 进入已回复 |
| 3 | 人工关闭线索 | 进入 `closed` |
| 4 | manual_reassign | 记录操作 |
| 5 | manual_reply | 记录操作 |
| 6 | manual_close | 记录操作 |
| 7 | closed 后恢复 | 不允许 |
| 8 | 审计记录 | 可追踪 |
| 9 | 回调 | 不误触发不应回调状态 |

------

## 16. 导出测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 导出 Excel | 生成 Excel |
| 2 | 时间范围 | 按范围导出 |
| 3 | 线索列表 | 包含目标字段 |
| 4 | 分配记录 | 可导出 |
| 5 | 微信通知任务 | 可导出 |
| 6 | 回复检测结果 | 可导出 |
| 7 | 超时记录 | 可导出 |
| 8 | 回调失败记录 | 可导出 |
| 9 | 人工处理记录 | 可导出 |
| 10 | invalid 原始事件 | 可导出 |
| 11 | 脱敏 | 第一版导出不脱敏 |
| 12 | 状态 | 导出不改变业务状态 |

------

## 17. 日志与脱敏测试

结合 `D:\zws\ask_next_Project\log-template` 探索结论，后续日志改造验收必须覆盖：

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 日志初始化 | 主服务 / Local Agent 初始化成功，不重复 handler |
| 2 | 普通日志 | 写入 `log/app.log` 或适配路径 |
| 3 | 错误日志 | ERROR 及以上写入错误日志 |
| 4 | 日志轮转 | 按天轮转 |
| 5 | 保留周期 | 符合配置 |
| 6 | webhook request_id | request_id / trace_id 贯穿 webhook |
| 7 | 任务追踪 | task_id / lead_id / agent_client_id 可追踪 |
| 8 | SECRET_KEY | 不出现在日志 |
| 9 | Authorization | 脱敏或 hash |
| 10 | token / cookie | 不明文输出 |
| 11 | 手机号 / 微信号 | 运行日志尽量脱敏 |
| 12 | 异常堆栈 | 使用 `logger.exception()` 或等价方式 |
| 13 | print | 关键链路不使用零散 `print` |
| 14 | 验签关闭 | 明确日志 |
| 15 | 生产关闭验签 | error / 启动失败 / 拒绝请求记录 |

------

## 18. 数据迁移与兼容测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 迁移前备份 | SQLite 已备份 |
| 2 | 脚本重复执行 | 可重复执行或有防重复保护 |
| 3 | 旧数据 customer_id | 回填默认客户 |
| 4 | 默认客户 | `default_customer` 或确认值创建成功 |
| 5 | 新增字段 | 不破坏旧查询 |
| 6 | 旧事件表 | `douyin_webhook_events` 仍可读 |
| 7 | 旧线索表 | `douyin_leads` 仍可读 |
| 8 | 迁移失败 | 可回滚 |
| 9 | Alembic 风险 | 记录未引入 Alembic 的风险 |
| 10 | 旧表 | 不直接删除旧表 |

------

## 19. 前端接口回归测试

| # | 页面 / 能力 | 验收点 |
|---|---|---|
| 1 | 线索列表 | 分页、状态、联系方式展示 |
| 2 | 线索详情 | 原始文本、提取结果、任务、检测 |
| 3 | 销售列表 | 新增、修改、停用 |
| 4 | 销售导入 | 模板、部分成功、错误行 |
| 5 | 关键词配置 | 保存和风险提示 |
| 6 | 工作时间配置 | 保存和展示 |
| 7 | 超时配置 | 默认值和修改 |
| 8 | Local Agent 状态 | 在线、离线、忙碌 |
| 9 | 微信任务列表 | 任务状态与失败原因 |
| 10 | 回复检测列表 | 命中关键词与状态 |
| 11 | 超时列表 | 超时和重分配 |
| 12 | 人工处理 | 重新分配、补录、关闭 |
| 13 | 导出 | 下载 Excel |
| 14 | invalid 展示 | 原始事件或 invalid 列表 |
| 15 | 分页 | page / page_size / total |
| 16 | 时间范围筛选 | 起止时间生效 |
| 17 | 状态筛选 | 对外四状态映射正确 |

------

## 20. 性能与并发基础测试

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | Webhook 连续请求 | 不重复建线索 |
| 2 | 高频重复事件 | 幂等稳定 |
| 3 | 200 QPS 设计检查 | 服务端 API / 数据库方案可支撑 |
| 4 | 2000 线索 / 天 | 查询和导出策略可接受 |
| 5 | Local Agent 并发 | 不并发操作微信 |
| 6 | 任务轮询抢占 | 不抢同一任务 |
| 7 | 大范围导出 | 不阻塞核心 webhook |

性能测试说明：

1. 200 QPS 是服务端 API / 数据库层面预留设计检查，不代表 Local Agent 微信执行能力。
2. Local Agent 必须串行执行微信任务。
3. 性能测试不得连接生产 webhook 或生产数据库。

------

## 21. 验收主链路测试

### 21.1 已回复主链路

```text
1. 商户完成抖音授权
2. 抖音 / 火山回调 webhook
3. webhook 签名通过
4. 原始事件入库
5. 解析用户私信纯文本
6. 提取手机号 / 微信号
7. 创建 / 更新有效线索
8. 自动分配销售
9. 创建微信通知任务
10. Local Agent 拉取任务
11. 本地微信通知销售
12. 销售回复有效关键词
13. Local Agent 检测回复
14. 状态进入已回复
15. 前端可查看
16. Excel 可导出
```

通过标准：

1. webhook、线索、分配、任务、检测、状态、导出均可追溯。
2. 运行日志含 request_id / task_id / failure_stage 等关键诊断字段。
3. 不出现 SECRET_KEY、完整 Authorization、token、cookie 明文。
4. Local Agent 检测链路保持只读。

### 21.2 超时重分配链路

```text
1. 有效线索分配销售
2. 销售未回复
3. 超过配置时间
4. 状态进入超时未回复
5. 触发重分配
6. 排除原销售
7. 超过最大次数进入人工处理或失败记录
```

通过标准：

1. 超时状态对外映射为“超时未回复”。
2. 重分配状态对外映射为“未分配”。
3. 超过 5 次后不无限循环。
4. 人工处理入口可追踪。

------

## 22. 测试优先级

### P0

1. Webhook 验签。
2. 原始 body 签名一致性。
3. 原始事件入库。
4. 私信 content 解析。
5. 联系方式提取。
6. 有效线索生成。
7. 幂等。
8. 销售分配。
9. Local Agent 发送任务。
10. Local Agent 检测任务。
11. 状态流转。
12. 失败回写。

### P1

1. invalid 展示与导出。
2. 销售管理与 Excel 导入。
3. 超时重分配。
4. 人工处理。
5. 日志与脱敏。
6. 数据迁移与旧数据兼容。
7. 前端筛选分页。
8. 导出。

### P2

1. 性能基础验证。
2. 旧路径兼容。
3. 更多联系方式边界样例。
4. 多商户扩展预留。
5. NewCarProject 预留接口。
6. 旧 douyinAPI 同步入口关闭策略。

------

## 23. 高风险测试项

| 风险 | 影响 | 必测项 |
|---|---|---|
| 生产验签开启导致全量 401 | webhook 全部失败 | staging 先验签、生产签名头确认、回滚策略 |
| 原始 body 被改写 | 签名不一致 | 空格、字段顺序、中文字符签名测试 |
| SECRET_KEY 泄露 | 安全事故 | 日志、事件表、响应体脱敏检查 |
| 联系方式误识别 | 错误生成线索 | 正例、反例、多联系方式测试 |
| invalid 进入分配 | 错误通知销售 | invalid 不分配、不建任务、不回调 |
| 状态混用 | 前端和回调错乱 | 线索状态、任务状态、检测状态分开验证 |
| 任务并发操作微信 | 误操作风险 | 运行锁、`agent_busy`、指定 task_id |
| detect_reply 写入或发送 | 安全事故 | 不调用 input_writer、不粘贴、不发送、不按 Enter |
| 迁移破坏旧库 | 数据丢失 | 备份、幂等迁移、旧数据可读 |
| 导出阻塞 webhook | 入口不可用 | 大范围导出与 webhook 并行检查 |

------

## 24. 测试前置确认项

执行代码阶段测试前，需要用户确认：

1. 生产 webhook 是否已经具备 `Authorization` 和 `X-Auth-Timestamp` 签名头。
2. 生产验签切换窗口、回滚策略和临时免验签审批规则。
3. `APP_ENV` / `ENV` / `DEPLOY_ENV` 的环境变量命名。
4. 生产缺少 `DY_SECRET_KEY` 时采用启动失败还是请求拒绝。
5. SQLite 迁移策略：Alembic 还是手写迁移脚本。
6. 默认 `customer_id` 和旧数据回填规则。
7. invalid 是否进入 `douyin_leads.status=invalid`，还是仅展示原始事件。
8. NewCarProject token / cookie / roles / merchant_id 字段结构。
9. 第一版是否继续保持 `sent=false`，只粘贴不发送。
10. 日志目录、保留周期、request_id / trace_id 字段名和脱敏规则。
11. 导出是否同步生成，还是异步 `export_tasks`。
12. 旧 `/integrations/douyin/sync-leads` 是否保留及关闭开关名称。

------

## 25. 推荐测试执行顺序

```text
1. 签名计算和联系方式提取单元测试
2. Webhook 验签接口测试
3. 原始事件与有效线索集成测试
4. 幂等和重复事件测试
5. 状态流转单元 / 集成测试
6. 销售分配与超时重分配测试
7. Local Agent mock 回归测试
8. 日志与脱敏检查
9. 数据迁移和旧库兼容测试
10. 前端接口与导出测试
11. 主链路 E2E 验收
12. 真机 Local Agent 最小链路验收
```

真机验收必须放在 mock 回归和安全门禁测试通过之后，不作为普通单元测试前提。

------

## 26. 本轮未执行说明

本轮是 P0-TESTPLAN-1 文档任务，没有执行以下事项：

```text
业务代码修改
测试代码修改
数据库模型修改
接口实现修改
配置默认值修改
```

## 27. AI 自动回复 outbox / 持久化任务验收（DY-CS-AUTO-REPLY-OUTBOX-1）

最终候选 `a245e231ad03e153d6b605801ded60ddbd2da1d3`（R2 第七次返修，父候选 `8e987642cd4fbd90057771cd47c2a0ffb4b10be3`）已通过独立测试 Test-Revision R2-T1（A1-A16 全部验收通过，任务级结论 PASS），并已通过普通快进推送集成至 `master@a245e231ad03e153d6b605801ded60ddbd2da1d3`（2026-07-25）：

- 复用 `AiAutoReplyRun` 表，新增 5 个 outbox 字段（SQLite 0036 + PG Alembic 0016）
- enqueue 在 webhook 外层事务内 flush pending run（仅 flush，不 commit）；拒绝空 `account_open_id`
- claim 使用条件 UPDATE 原子租约（300 秒），线程唯一 lease_owner + commit 后返回；UPDATE 含退避时间条件
- `_add_run` upsert：outbox 路径改为原子条件 UPDATE 校验 `expected_status=processing` + 原始 owner + 未过期租约 + `rowcount`，禁止 ORM setattr 逐字段覆盖；非 outbox 路径保留 ORM 兼容
- **guarded transition 原语 + lease 上下文 + cycle 单飞锁下沉至 outbox service**：强制校验 `run_id`/`expected_status`/原始 `lease_owner`/`lease_expires_at>now`/`rowcount==1`
- claim 原始 owner 显式贯穿：`send_ai_auto_reply_for_run` 增加 `lease_owner` 参数，dry-run 调用时显式传入，非 outbox 路径传空串兼容；send 不再重读 DB 当前 owner；`_finish_run` 返回 False 时立即终止不进入发送
- **`_run_with_session_for_outbox` 与 `_process_one` 强制非空 lease_owner**：空值属于非法状态（claim 必然写入线程唯一 owner），失败关闭并输出 stage/failure_stage，不得降级为无租约处理
- **检查点前置**：send 在第一个写库动作前先取得 guarded 检查点 `decided → send_processing`（内容规范化合并进该原子 UPDATE），gate_results 在局部 dict 累积，仅在检查点/终态原子写入；区分检查点前(`decided`)/后(`send_processing`) skip 终态；检查点后 8 个跳过路径（outbound_after_trigger / latest_message_not_customer / latest_message_changed / send_context_unavailable / send_context_message_changed / send_context_account_mismatch / send_context_customer_mismatch / context_expired）通过 `_mark_send_skipped_after_checkpoint(gate_results_json=...)` 传入当前局部累积 gate_json，由单条原子 guarded UPDATE 同时写状态/原因/gate_results 并清租约，保留 send_gate_passed 与 manual_takeover 诊断
- **gate_results 纯内存累积**：`_merge_gate_results` 改为纯函数，在局部 dict 合并多次 gate section，不修改任何 Session 管理的 ORM 属性（不写 `run.gate_results_json`），由 guarded UPDATE 一次性写入
- **终态单条原子 guarded UPDATE + 原子清租约**：`_terminal` 一次性写状态/诊断/清租约；`_finish_run` 对非 decided 终态（blocked/skipped/failed）原子清租约，`_add_run` outbox 终态 upsert 清租约，`_handle_llm_failure` retry_wait/failed 清租约；**只有马上进入真实发送的 real_send_candidate decided 继续持有租约**，dry-run 模式 decided（不进发送）补 else 分支原子清租约
- 发送状态检查点：`decided → send_processing → send_authorized` 全部 guarded + 检查点续租 → 终态 guarded + 清租约；租约丢失 `rowcount=0` 时不覆盖恢复器或新 Worker 状态、不触发 `mark_ai_replied`；`sent` 终态 rowcount==1 后才同步决策日志
- `send_authorized` 崩溃对账：原子 `EXISTS`/`NOT EXISTS` UPDATE，存在 sent 发送流水 → sent，否则 → send_unknown；禁止自动重发；`recovered` 仅累计实际 rowcount
- LLM 失败自动重试：`attempt_count <= MAX_RETRIES` → `retry_wait` + 退避（attempt 1→60s、2/3→300s、4→`failed` 终态）；`last_failure_stage=pre_send_temporary_failure`
- send 失败分类：`error_code=upstream_business_error` → `failed`；网络/超时/HTTP/非法 → `send_unknown`
- recover 恢复过期租约的 processing/send_processing 到 pending；send_authorized 按发送流水对账
- compensate 补偿 15 分钟窗口内缺失的客户私信事件（保存点隔离，跳过无商户/无账号）
- BackgroundTasks 仅唤醒 outbox claim（受总开关控制），不直接执行旧 `run_ai_auto_reply_job`；scheduler 与 webhook wake 共用 cycle 单飞锁；`run_outbox_cycle` 在 try 内创建 Session，构造失败时 try/finally 释放单飞锁
- manual retry 使用单条原子条件 UPDATE（merchant_id + failed + 白名单 + `NOT EXISTS` 发送流水），消除 TOCTOU
- 调度器默认关闭（`AI_AUTO_REPLY_OUTBOX_ENABLED=false`）；10 个 outbox 变量已在三个 env 模板登记且默认值与 `config.py` 一致
- 执行窗口自测（`python -m pytest tests/test_ai_auto_reply_outbox_service.py tests/test_ai_auto_reply_send_service.py tests/test_ai_auto_reply_dry_run.py tests/test_env_profile_templates.py tests/test_douyin_webhook.py -q`）：258 passed；本任务专项、新增并发/租约回归与 outbox 状态机直接相关测试 0 failed（含检查点后跳过路径原子写 gate_results + 清租约 + 不调用真实发送断言），指定回归 0 个新增失败
- 独立测试 Test-Revision R2-T1（A1-A16 全部验收通过，任务级结论 PASS）：主专项 258 passed、迁移/API/合同 49 passed、并发热点 10 轮 40 passed，合计 347 passed；另有 2 个经 Base（8e98764）/ Candidate（a245e23）同环境对照确认的范围外基线失败：① `test_active_binding_calls_9100_with_history_and_records_decision_log`（IndexError，根因在 `douyin_conversation_history_service.py`，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域）；② env `test_all_code_variables_are_classified`（未登记变量均为 AI_EDIT 冻结模块 / DAILY_REPORT / LOCAL_AGENT / NEWCAR_AUTH，不在本任务 Allowed-Files）；Candidate 0 个新增失败
- 已通过普通快进推送集成至 `master@a245e231ad03e153d6b605801ded60ddbd2da1d3`；PostgreSQL/MVCC 验证见第 29 节（DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1，P1-P9、C1-C4 全部 PASS），未验证生产调度、迁移和恢复，未连接生产环境，未发送真实私信、自动回复或微信消息，未运行全仓测试，尚未部署或发布

## 28. AI 自动回复 outbox 重启恢复测试（DY-CS-AUTO-REPLY-OUTBOX-RESTART-RECOVERY-1）

最终候选 `a7f924d02712fd942a1b9f069bf4b9c40bf6c8fe`（R1，父候选 `e18b3524b4d51dc3f51b03bb387510355f92ab1b`）已通过独立测试 Test-Revision R1-T1，R1-R11 全部通过，任务级结论 PASS（2026-07-25）：

- pytest 父进程编排全新 Python 子进程，共享 `tmp_path` 临时文件 SQLite，验证 outbox 仅依赖已提交数据库状态完成恢复、领取、对账和去重，全程禁止真实外部动作
- 子进程在 `import app.database` 前绑定临时 `DATABASE_URL`、剥离继承的 TOKEN/SECRET/PASSWORD/API_KEY、关闭自动回复与真实发送开关；安全处理器用真实 guarded UPDATE 推进到 `blocked` 终态并清租约，LLM/9100/抖音/微信/socket 全部 patch 为"调用即失败"
- R1 进程隔离与落盘；R2 `pending` 重启安全处理一次；R3 真实 claim 后 `os._exit` 过期恢复处理一次（`recovered_failure_stage=lease_expired`）；R4 过期 `send_processing` 恢复一次；R5 `retry_wait` 未到期不领取、到期领取一次；R6 `send_authorized` 有 sent 流水对账为 `sent` 不重发；R7 无流水对账为 `send_unknown` 不重发；R8 连续两次重启不重复副作用；R9 调度器关闭不领取（日志含 `reason=disabled`）；R10 空 `lease_owner` 失败关闭（日志含 `stage=process_one`/`failure_stage=missing_lease_owner`）；R11 外部调用为零（`_run_safe_cycle` 强制断言 `calls["count"]==0`，R3/R4/R5/R8 断言 `external_calls==0`）
- 独立测试数字：专项 `11 passed, 0 failed`；连续 10 轮共 `110 passed, 0 failed`；完整指定回归 `248 passed`、1 个范围外基线失败（`test_active_binding_calls_9100_with_history_and_records_decision_log`，根因在 `douyin_conversation_history_service.py`，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域），Candidate 0 个新增失败
- 已通过普通快进推送集成至 `master@a7f924d02712fd942a1b9f069bf4b9c40bf6c8fe`；本地跨进程 SQLite 重启恢复测试已在专用 PostgreSQL 数据库补齐 MVCC 验证（见第 29 节 DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1，P1-P9、C1-C4 全部 PASS），未验证生产调度、迁移和恢复，未连接生产环境，未发送真实私信、自动回复或微信消息，未运行全仓测试，尚未部署或发布

## 29. AI 自动回复 outbox PostgreSQL/MVCC 恢复测试（DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1）

最终候选 `df8644d828680a75ff955db59c546d4ba1caa729`（R1，Implementation-Base `70f3e22b175e415ec6b1824e1e8f2e6a0a96ea6d`，直接父提交 `08ccdac9dd3128784d150b691eb52437ae28b169`，含 R1-REPAIR-1/R1-REPAIR-2A 返修及 R2/R3 测试加固）已通过独立测试 Test-Revision R1-T1，P1-P9、C1-C4 全部 PASS，任务级结论 PASS（2026-07-27）：

- 在本地专用 PostgreSQL 测试库 `auto_wechat_outbox_test`（Alembic 0016 head）验证 outbox 跨进程可见性、20 路 MVCC 领取竞争、租约恢复、发送对账与旧 Worker 防覆盖语义，全程禁止真实外部动作
- R1-REPAIR-1 修复 0016 迁移链断裂：`down_revision` 从错误缩写 `"0015"` 修正为真实前驱 `"0015_ai_edit_material_library"`，迁移图唯一 head=0016；静态合同测试改为断言完整真实 revision 并新增 `ScriptDirectory` 图解析测试
- R1-REPAIR-2A 对齐 `AiAutoReplyRun.gate_results_json` 方言感知类型：自定义 `TypeDecorator`（`impl=Text`，PostgreSQL 用 `JSONB(none_as_null=True)`、SQLite 用 `Text()`），PostgreSQL 写入前 `json.loads` 解析为对象/数组避免双重编码、读回后 `json.dumps` 重新序列化为字符串，对外保持 `str|None` 契约，`None` 写为 SQL NULL，非法 JSON 字符串在 PostgreSQL 写入前抛 `JSONDecodeError`；不修 `ReturnVisitRun.gate_results_json`（其 PG 迁移本就是 Text，一致）；R2/R3 为测试加固（P7 sent 流水夹具 Core insert 省略范围外 JSONB 列、P8 新租约与新 Worker 诊断值防覆盖断言）
- P1 安全门合同（`--postgres-smoke`/`--namespace`/`--ready-file`/`--start-file`/`--lease-owner` CLI 暴露、`_validate_smoke_database_url` 安全门）；P2 Alembic 0016 schema（jsonb/tz 字段/索引/`alembic_version=0016`）；P3 跨进程提交可见性
- P4 20 路子进程文件门禁 claim 连续 10 轮单胜（`attempt_count=1`/`lease_owner` 非空/胜出者 `run_ids` 唯一）；P5 `os._exit(23)` 后租约未过期不领取/过期恢复一次（`recovered_failure_stage=lease_expired`）；P6 `retry_wait` 到期边界；P7 `send_authorized` 有/无 sent 流水对账（`sent`/`send_unknown`，租约清空，仅 True 分支 1 条预置流水）；P8 旧 owner `guarded-block-once` `rowcount=0` 不覆盖新 owner/新租约/新诊断值（`block_reason='pg_new_owner_state'` 保持）；P9 `external_calls=0`/意外流水 0/namespace 残留 0/日志无明文凭据
- C1 `_GateResultsJSON` PostgreSQL/SQLite 类型及字符串合同（后续第 30 节泛化为共享类型 `_JSONStringJSONB`）；C2 SQLite 重启恢复 R1-R11 无回归；C3 outbox/send/dry-run/webhook 相邻回归无 Candidate 新增失败；C4 编译、范围、线性、工作区和差异检查
- `_claim_test_webhook_event` 注释合同（helper 规避 ORM Text→JSONB 类型错误，不声称已存为对象；webhook JSON 字符串标量双重编码问题已由后续 parity 任务 `P3-9000-PG-SCHEMA-ORM-JSONB-PARITY-REPAIR-1` 闭合，见第 30 节）
- 独立测试数字：schema 合同 `11 passed`、PostgreSQL 专项 `22 passed, 0 skipped`、连续 10 轮共 `220 passed`、SQLite 重启恢复 `11 passed`、状态机回归 `149 passed + 1` 个范围外基线失败（`test_active_binding_calls_9100_with_history_and_records_decision_log`，根因在 `douyin_conversation_history_service.py`，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域）、webhook 回归 `89 passed`，Candidate 0 个新增失败
- `external_calls=0`、意外流水=0、namespace 残留=0、遗留子进程=0；专用 PostgreSQL 数据库连接是唯一允许的网络传输
- 已通过普通快进推送集成至 `master@df8644d828680a75ff955db59c546d4ba1caa729`；只验证本地专用 PostgreSQL 数据库，不等于生产验证，未验证生产调度、生产迁移和生产恢复，未连接 staging/production，未真实发送，未运行全仓测试，尚未部署或发布

## 30. 9000 PostgreSQL JSONB/ORM 一致性首批返修（P3-9000-PG-SCHEMA-ORM-JSONB-PARITY-REPAIR-1）

最终候选 `9a2f1aabb7725de6e12822ce194c1d8ad15c2904`（R1，Base `1042a07ab3b4267586ea5b9fc5e69ceed9f1099a`，7 个单父线性提交，8 个允许实现/测试文件）已通过独立测试 R1，J1-J16、B1-B8 全部 PASS，任务级结论 PASS（2026-07-27）：

- `9a2f1aa` 已进入远端 `master@020ab730bae8ac2c570ce4e0e185f203b62b08e4` 的线性历史
- 允许范围：`app/models.py`、`app/services/douyin_webhook_idempotency_service.py`、`app/services/webhook_event_service.py`、`app/services/douyin_merchant_isolation.py`、`app/services/douyin_workbench_conversation_service.py`、`app/services/ai_reply_decision_log_query_service.py`、`tests/test_douyin_webhook_atomic_idempotency.py`、`tests/test_9000_postgres_jsonb_orm_parity.py`
- `_GateResultsJSON` 泛化为共享类型 `_JSONStringJSONB`（`impl=Text`，PostgreSQL 用 `JSONB(none_as_null=True)`、SQLite 用 `Text()`，PG 写入前 `json.loads` 解析避免双重编码、读回 `json.dumps` 重新序列化为字符串，对外保持 `str|None` 契约；JSON 文本 `"null"` 含空白形式跨方言统一映射为 SQL NULL，新 Session 读回 `None`；非法 JSON 在 PG 写入前抛 `JSONDecodeError`）
- 首批 11 个 JSON 字符串字段映射：`AiAutoReplyRun.gate_results_json`、`DouyinWebhookEvent.raw_body`/`parsed_content_json`、`DouyinPrivateMessageSend.request_body_json`/`response_body_json`、`AiReplyDecisionLog` 的 `risk_flags_json`/`tags_json`/`rag_sources_json`/`source_chunks_json`/`allowed_category_keys_json`/`raw_response_json`
- 新增 `_IntegerBoolean`（`impl=Integer`，PostgreSQL 编译 BOOLEAN、SQLite 编译 INTEGER；绑定时 0/1 转 False/True（PG）或保持整数（SQLite），读回仍为严格 int 0/1，`None` 写 SQL NULL；损坏值如 `"0"`、`2`、字符串抛 `ValueError`），映射 7 个字段（`DouyinPrivateMessageSend.manual_confirmed`/`auto_send`、`AiReplyDecisionLog.manual_required`/`llm_used`/`rag_used`/`upstream_auto_send`/`final_auto_send`），`is_effective` 保持普通 `Boolean`
- webhook 原子占位移除手工 `cast(JSONB)`，由列类型完成 JSONB 参数绑定
- JSONB 文本筛选显式 `cast(column, Text).like(...)`（4 个服务）
- 真实 `_pg_url()` 接受/拒绝边界：`postgresql+psycopg`/`127.0.0.1`|`localhost`/`5432`/`auto_wechat_outbox_test`/无 query fragment（6 类拒绝 + 2 主机接受，直接调用 `_pg_url()` 而非复制判断逻辑）
- J1-J16：J1/J2 共享类型编译 JSONB/TEXT、J3 字符串合同 + JSON "null" 归一 + 非法 JSON 失败、J4 ORM 写入读回 webhook JSON 字符串、J5/J6 claim 存对象非字符串标量、J7 20 路×10 轮单胜、J8 重复事件不产生第二个有效业务事件（由既有 webhook 原子幂等回归覆盖）、J9 send_service 写原生 JSONB（无真实网络）、J10 decision_service 6 字符串字段 + 风险筛选、J11 webhook/merchant/workbench 筛选 cast TEXT、J12 SQLite 相邻回归无回归、J13 namespace 残留 0（pg_case fixture finally 断言四表计数 (0,0,0,0)）、J14 Alembic 0016 schema 且无 `create_all`、J15 Candidate 新增失败 0、J16 编译/范围/线性/工作区/差异检查通过；全程无真实外部调用（`call_douyin_openapi` 全程 patch 为本地替身）、无遗留线程或子进程（ThreadPoolExecutor 正常关闭、pg_case fixture 清理）
- B1-B8：B1 `_IntegerBoolean` PG=BOOLEAN/SQLite=INTEGER、B2 0/1/False/True/None 双方言绑定、B3 非法值抛 ValueError、B4 7 字段使用该类型且 `is_effective` 不变、B5 真实 PG 写入成功、B6 新 Session 读回严格 int 0/1（`type(value) is int`）+ PG `pg_typeof=boolean`、B7 manual_required/llm_used/rag_used 查询筛选限定本 namespace 命中、B8 J1-J16 与 SQLite 回归
- 独立测试数字：PostgreSQL 专项 `38 passed, 0 skipped`（J7 内部 20 路×10 轮单胜，专项另连续 3 轮通过）、webhook/atomic/workbench `157 passed`、outbox/send/dry-run `149 passed + 1` 个范围外基线失败（`test_active_binding_calls_9100_with_history_and_records_decision_log`，IndexError 行 580，Base/Candidate 同环境一致）、PostgreSQL MVCC `22 passed`、SQLite 重启恢复 `11 passed`，Candidate 0 个新增失败
- `020ab730bae8ac2c570ce4e0e185f203b62b08e4` 将 `DouyinLead.raw_data`/`all_extracted_contacts` 改用 `_JSONStringJSONB`，该提交不属于 `9a2f1aa` 的 R1 独立测试报告覆盖范围，不继承 38 passed 结论
- 只验证本地专用 PostgreSQL 数据库，不等于生产验证，未验证生产调度、生产迁移和生产恢复，未连接 staging/production，未真实发送，未运行全仓测试，尚未部署或发布

后续代码阶段应按本文逐项拆分测试用例和验收报告。
