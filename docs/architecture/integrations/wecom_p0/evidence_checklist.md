# P0 企业微信官方能力实证 — 证据清单

> 状态：P0_IN_PROGRESS（等待外部资源）
> 决策依据：WECOM_THIRD_PARTY_APP_TECHNICAL_DESIGN_V1_CONVERGENCE.md §10
> 执行依据：WECOM_THIRD_PARTY_APP_IMPLEMENTATION_PLAN_V1.md §2
> 基线：WECOM_THIRD_PARTY_APP_API_EXPLORATION.md（已锁定 CONFIRMED / NOT_CONFIRMED）
> 约束：零代码 / 零 migration / 零生产改动 / 零提交推送。P0 只做证据与报告。

## 0. 本清单用途

P0 验收标准：**每个生产阻断项都有官方当前证据、真实请求/响应摘要、失败分类和回滚方式，Owner 批准后才能进入 P1。**

本清单把 8 类证据准备拆成可勾选项，逐项标注来源、现状、所需外部资源、失败分类与回滚方式，作为 P0 追踪与验收骨架。

---

## 1. 外部前置资源（须 Owner / 运维提供，P0 实测的硬前提）

| # | 资源 | 用途 | 现状 | 提供方 |
|---|---|---|---|---|
| R1 | 服务商主体账号（个人开发者或企业服务商） | 注册第三方应用，获取 suite_id / suite_secret / token / EncodingAESKey | 缺失 | Owner / 公司决策 |
| R2 | 测试企业（可扫码授权） | 扫码安装授权、选可见范围、发卡片、回调查收 | 缺失 | Owner |
| R3 | 可回调的公网 URL（或本地隧道） | 9000 接收 suite_ticket / 授权事件 / template_card_event 回调 | 缺失 | 运维 |
| R4 | 测试销售成员（测试企业内可见范围） | 成员同步、绑定、Template Card 派单与按钮反馈 | 缺失 | Owner |
| R5 | 基础接口许可（测试企业） | 发消息 / 收回调前置许可；未许可成员 = unlicenseduser | 缺失（收费规则门禁内） | Owner / 企微商务 |
| R6 | Credential Encryption Key 项目级来源 | 永久码 / suite_ticket 加密保存用途（P1 才需，P0 确认来源即可） | 待定 | Owner |

> 现状结论：R1~R5 全部缺失，P0 的"实测"类证据项当前全部 BLOCKED_BY_RESOURCE。本地已完成：证据骨架、现状归档、资源需求书。

---

## 2. 证据项清单（8 类）

标记说明：`✅`= 已有官方文档证据；`🔶`= 部分证据 / 门禁内；`⛔`= 须实测（缺资源）；`—`= 不适用

### E1 服务商账号、测试企业与授权范围

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| 第三方应用注册/服务商主体 | 官方 /90594 /90595 | ✅ | 主体资质不符 | 换主体重新注册 |
| 扫码安装授权 URL 构造 | 官方 /90597 | ✅ | URL 参数错误 | 无副作用，重试 |
| 管理员选择可见范围（allow_user/party/tag） | 官方 /90583 | ✅ | 范围选择错误 | 重新设置可见范围 |
| 多企业每企业一个授权（permanent_code 按 merchant 隔离） | 官方 /100776 | ✅ | — | — |

### E2 suite_ticket 推送与签名/AES 配置

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| suite_ticket 10min 推送、30min 有效 | 官方 /90628 | ✅ | — | — |
| 回调签名 + AES 加解密（EncodingAESKey） | 官方 /91116 /90613 | 🔶 | 验签/解密失败 | 记录 fail-closed，不处理 |
| 回调 URL 验证（echostr）GET 应答格式 | 官方 /91116 | 🔶 | ACK 格式不符 | 官方侧改配置 |
| 第三方接收消息配置页细节 | 官方配置页（登录态） | ⛔ | 配置不可达 | 官方侧调整 |

### E3 Template Card 发送、按钮回调、卡片更新真实样本

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| message/send 发送模板卡片（button_interaction） | 官方 消息发送 | 🔶 | 许可/可见范围错误（81013/60011） | 按错误码修正 |
| task_id / EventKey 原样回传可绑定 lead | 官方 模板卡片事件 | ✅ | — | — |
| 按钮回调 template_card_event 真实载荷 | 官方 回调事件 | ⛔ | 事件字段差异 | 按官方样本修正解析 |
| update_template_card 置灰/更新接口 | 官方 卡片更新 | 🔶 | 更新失败不回滚业务 | 业务已提交不回退 |

### E4 第三方应用网页授权 appid 与成员身份换取链

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| 第三方网页授权构造链接 appid 取值（suite_id 或 corpid） | 官方 /10110 等（登录态） | ⛔ | appid 取值错误 | 按实测修正 |
| open_userid 换取（第三方成员身份主线） | 官方 成员 ID 体系 | ✅ | — | — |
| 销售自绑定所需的成员身份证明链 | 官方 网页授权 | ⛔ | 身份证据不足 | 降级为管理员显式绑定 |

### E5 取消授权、授权变更、成员移出范围样本

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| cancel_auth / change_auth 事件 | 官方 /100964 | 🔶 | 回调不保证 100% 送达 | get_auth_info 对账兜底 |
| permanent_code 在 cancel_auth 后是否自动失效 | 官方未说明 | ⛔ | 凭证复用风险 | 置 INVALID + fail-closed |
| 成员移出可见范围后的成员状态 | 官方 成员 API | ⛔ | 状态不同步 | 快照定期刷新 |

### E6 官方许可、接口收费、可见范围证据

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| 基础接口许可（发消息/收回调） | 官方 /90236 等 | 🔶 | 未许可成员无权限 | 申请许可 |
| 服务商/接口许可收费规则 | 官方 /10012 /10013 /10020（登录态） | ⛔ | 成本评估缺失 | 商务确认 |
| 未许可成员返回 unlicenseduser / 81013 | 官方 错误码 | 🔶 | 全无权限 81013 | 申请许可后重试 |

### E7 callback 稳定事件标识与 ACK 格式

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| 回调稳定事件唯一标识（provider_event_key 可用字段） | 官方 回调事件 | ⛔ | 标识不稳定 | 取权威字段做唯一键 |
| 应答格式（success 或空串）与重试策略 | 官方 回调 | 🔶 | ACK 时序不符 | 官方侧调整配置 |
| 重试/幂等（重复回调去重） | 官方 回调 | 🔶 | 重复投递 | provider_event_key UNIQUE |

### E8 脱敏 fixture、回放脚本、证据清单

| 子项 | 来源 | 现状 | 失败分类 | 回滚方式 |
|---|---|---|---|---|
| 脱敏 request/response fixture 归档规范 | 本清单 §3 | 🔶 | 泄露敏感字段 | 打码规范约束 |
| 回放脚本（验证解析与幂等） | P0 后期 | ⛔ | 无真实样本无法回放 | 样本就绪后补 |
| 证据清单（本文档） | 本清单 | ✅ | — | — |

---

## 3. 6 项 UNKNOWN_OFFICIAL_CAPABILITIES 补证（来自 API_EXPLORATION §19）

| # | 未知项 | 现状 | 补证路径 | 对 P1 的影响 |
|---|---|---|---|---|
| U1 | 第三方网页授权 appid 取值 | ⛔ | R1+R3 实测 | 销售自绑定可行性与 URL 构造 |
| U2 | 第三方接收消息配置页细节 | ⛔ | R1 官方后台 | callback 配置 |
| U3 | cancel_auth 后 permanent_code 是否失效 | ⛔ | R1+R2 实测 | 授权状态机 INVALID 策略 |
| U4 | 同一自然人换企业后 open_userid 是否相同 | ⛔ | R2 多企业实测 | 成员身份跨企业语义 |
| U5 | 许可/接口收费规则 | ⛔ | R1 商务/后台 | 成本与 P6 放量 |
| U6 | 关键错误码 40014/43004/60011 正文 | 🔶 | 官方错误码附录 | 失败分类准确性 |

---

## 4. 生产阻断项 → 证据 → 验收映射（API_EXPLORATION §18 B1~B6）

| 阻断项 | 证据项 | 验收条件 | 现状 |
|---|---|---|---|
| B1 独立服务商主体 | E1 + R1 | suite_id/suite_secret 可用，授权闭环可跑 | ⛔ 缺 R1 |
| B2 suite_ticket 持续接收 | E2 + R3 | 9000 常驻回调稳定收 ticket 并换 token | ⛔ 缺 R3 |
| B3 基础接口许可 | E6 + R5 | 发消息/收回调可用，无 81013 | ⛔ 缺 R5 |
| B4 回调可靠投递兜底 | E5/E7 | 对账任务设计有官方依据 | ⛔ 缺 R3 实测 |
| B5 M06 剪辑本地执行面 | 记录存在（不动作） | M06 独立任务单建立 | ✅ 记录 |
| B6 门禁内 NOT_CONFIRMED 项 | §3 U1/U2/U5 | 6 项 UNKNOWN 全部补证或明确降级 | ⛔ 缺 R1 |

---

## 5. P0 验收门（进入 P1 前必须全部满足）

1. R1~R5 外部资源就绪，6 项 UNKNOWN（U1~U6）每项均有官方当前证据或明确降级说明；
2. 8 类证据项（E1~E8）每项有：官方当前证据 + 真实请求/响应摘要 + 失败分类 + 回滚方式；
3. 脱敏 fixture 已按 §3 规范归档，可回放验证解析与幂等；
4. Owner 对证据清单逐项签字，批准进入 P1。

> 当前结论：P0 处于 **BLOCKED_BY_RESOURCE**（缺 R1~R5）。本地侧已完成证据骨架与现状归档；补证实测等待 Owner 提供资源。

---

## 6. P0-WECOM-CALLBACK-VERIFICATION-PROBE-1 本地验证状态（2026-08-20）

> 任务：P0-WECOM-CALLBACK-VERIFICATION-PROBE-1（L3 / OWNER_APPROVED / MINIMAL_IMPLEMENTATION_PROBE）
> 范围：仅协议层（签名 + AES 解密 + 最小事件识别），零 migration / 零业务写入 / 零 19000 改动。

### 本地已实现（仅协议层，零业务）

| 文件 | 职责 |
|---|---|
| `app/integrations/wecom/crypto.py` | 签名校验（SHA1 字典序）、AES-256-CBC 解密（PKCS7）、外层 Encrypt 提取、最小 envelope 解析（XXE 拒绝） |
| `app/routers/wecom_callback.py` | GET = URL 验证（验签 + 解密 + 返回精确明文）；POST = 验签 + 解密 + 事件识别 + 安全日志 + ACK `success` |
| `app/config.py` | `WECOM_CALLBACK_TOKEN` / `WECOM_CALLBACK_ENCODING_AES_KEY` / `WECOM_SUITE_ID`（仅环境注入，缺省 fail-closed） |
| `tests/test_wecom_callback_probe.py` | 19 项协议测试（GET 8 + POST 11），全部 PASS |
| `requirements.txt` | 新增 `cryptography>=42.0.0`（唯一新增依赖，标准库无 AES-256-CBC） |

### 本地验证证据（脱敏）

| 证据项 | 状态 | 证据 |
|---|---|---|
| callback URL 验证（GET） | ✅ PASS | 19/19 pytest；验签/解密/精确明文返回 PASS；签名错、密文改、错 Token、错 AESKey、缺参、suite 不匹配、config 缺失 → 均 fail-closed 400 |
| signature verification | ✅ PASS | 恒定时间比较；无效签名拒绝 |
| AES decrypt | ✅ PASS | AES-256-CBC + PKCS7 + receiveid 校验；非法密文/填充拒绝 |
| 指令回调 ACK（POST） | ✅ PASS | suite_ticket / create_auth / change_auth / cancel_auth 识别 → `success`；未知事件 → ACK + IGNORED_UNSUPPORTED；重复 ticket 幂等安全 |
| 事件识别（InfoType） | ✅ PASS | 基于解密后 envelope 的 InfoType 字段，不靠 URL 猜事件类别 |
| 真实套件回调保存 | ⛔ BLOCKED_BY_EXTERNAL_RESOURCE | 缺 R1（服务商账号）/ R3（公网回调 URL 部署） |
| 真实 suite_ticket 投递 | ⛔ BLOCKED_BY_EXTERNAL_RESOURCE | 缺真实 secret + 生产部署 |
| 数据回调配置 | ⛔ BLOCKED_BY_EXTERNAL_RESOURCE | 同一物理 URL，待真实后台确认是否需分命令/数据两套 Token |

### 日志安全约定（已实现）

- 日志只记 `stage` / `result` / `error_code` / `ts` + 脱敏 metadata（event_type、suite_id、ticket_hash 前 8 位、AuthCorpId）
- 不打印 SuiteTicket 明文 / Token / AESKey / permanent_code / 明文 XML；响应仅 `success` / `verification failed`

### 真实验证待办（Owner 提供资源后执行，步骤见任务书 §15）

1. Owner 在部署环境注入 `WECOM_CALLBACK_TOKEN` / `WECOM_CALLBACK_ENCODING_AES_KEY` / `WECOM_SUITE_ID`（不入 Git / docs）
2. 部署后验证 `https://merchant.xiaogaoai.cn/api/integrations/wecom/callback` HTTPS 可达
3. 企微后台保存指令回调 URL → GET 验证 PASS
4. 收到 suite_ticket → 验签/解密/识别 → ACK `success` → 后台不持续报错
5. 再验证数据回调 URL 是否可保存（若后台要求独立 Token/AESKey，STOP 上报 Owner，禁止自行分 URL 或 key guessing）

### 严格排除（已遵守）

无 Alembic migration / 无 wecom_suite_runtime 建表 / 无 authorization / member / binding 表 / 无 permanent_code / 无 token 缓存 / 无消息发送 / 无 Template Card / 无 Lead feedback / 无 durable inbox / 无 worker / 无 H5 / 无前端 / 无 19000 修改 / 无 MVC 重构。

---

## 7. P0-WECOM-REAL-CALLBACK-VERIFICATION-1 状态（2026-08-20）

### 已收口

```text
PROBE_COMMIT        = 7d0fe3e（feat: 企业微信回调验证Probe——GET/POST callback 验签解密与事件识别）
                      （仅含 7 个 Probe 代码文件；设计文档 IMPLEMENTATION_PLAN / V1_CONVERGENCE 保持未跟踪未混入）
CRYPTOGRAPHY_IMAGE  = 机制确认：Dockerfile → requirements-docker.txt（-r requirements.txt）→ cryptography>=42.0.0，
                      候选 API 镜像构建时自动安装；实际构建/推送由部署机执行
DB_CHANGE           = 0（Probe 无 migration，镜像 alembic head 不变）
```

### 真实回调部署 = PASS（2026-08-20 已完成）

通过生产 SSH（xg-prod）按项目正式发布入口 `prod_release.py`（inspect → deploy --dry-run → apply → verify）完成。

**已收口 commit 链**（三次受控发布）：

```text
7d0fe3e  feat: 企微回调验证Probe（初始，9000 内部带 /api 前缀）
8a120b9  fix: 路由前缀对齐项目惯例（9000 内部去 /api，nginx 剥离后匹配）→ 首个可用部署
ec506ef  fix: verifyURL GET 不再按 suite_id 校验 receiveid（实测 receiveid 为 corpid）
```

### 真实验证结果（脱敏）

```text
PROBE_COMMIT                 = 7d0fe3e
DEPLOYED_COMMIT              = ec506ef（最终生效，含路由前缀 + verifyURL receiveid 两项修复）
DEPLOYED_IMAGE               = xg-ai-system-api:release-ec506ef57c29
CRYPTOGRAPHY                 = 50.0.0（容器内 import 验证）
HTTPS_REACHABLE              = YES（外网 400/200 可达，非 404/502/503）
ROUTE_MOUNTED                = YES（nginx 剥离 /api → 9000 /integrations/wecom/callback）
REAL_COMMAND_CALLBACK_SAVE   = PASS（指令回调保存成功，suite_ticket 持续到达）
REAL_GET_VERIFICATION        = PASS
  证据：3 次 GET result=ok（09:16:27/28/55）+ 企微真实历史请求重放返回 200 明文
  关键协议事实：verifyURL 的 echostr 加密 receiveid 是 corpid（实测 wwaa...18位），
  非 suite_id（suite_ticket 推送才用 suite_id=ww9b...）；修复后 GET 不强制 receiveid 校验，
  来源可信由 msg_signature 验签保证；POST 保留 receiveid==suite_id 校验（已实证匹配）
REAL_SUITE_TICKET_RECEIVED   = PASS
  证据：09:07:20 / 09:17:22 / 09:27:22 三个 ticket（每 10 分钟稳定投递），
  event_type=suite_ticket / ticket_hash 前缀各不同（319eaae5 / 16195fe8 / 0eaf0d88）
  / ACK success 返回 200，后台无持续报错
REAL_DATA_CALLBACK_SAVE      = PASS（同一 URL + 当前 Token/AESKey 保存成功）
SAME_PHYSICAL_CALLBACK_URL   = VALIDATED（指令+数据共用同一物理 URL，无 ReceiveId/Token/AESKey mismatch）
SECRET_EXPOSURE              = NO（未输出 Token/AESKey/SuiteTicket 明文/解密全文；仅 event_type/stage/result/error_code/ticket_hash）
DB_CHANGE                    = 0
MIGRATION                    = 0
P1_CHANGE                    = 0
19000_CHANGE                 = 0
P0_STATUS                    = PASS
```

### 部署过程中的经验（供后续 P1 参考）

1. 生产→GitHub 网络慢（raw.githubusercontent 超时）：部署前用
   `GIT_HTTP_LOW_SPEED_LIMIT=1 GIT_HTTP_LOW_SPEED_TIME=600` 手动 `git fetch origin` 先对齐 refs。
2. 9000 内部路由一律不带 `/api` 前缀（nginx `location ^~ /api/ { proxy_pass ...:9000/; }` 剥离），
   新路由必须遵循；`prod_release.py` 目标 image 用 12 位短 sha（`_target_image_tag`）。
3. 后端镜像必须用 `Dockerfile.backend.dev`（生产 compose 的 dockerfile；`Dockerfile` 的 CMD
   在 production 会 exit 1）。
4. 企微 verifyURL receiveid=corpid 与 suite_ticket receiveid=suite_id 语义不同——P1 回调协议层保持此区分。

### P0 收口最终状态（WECOM-P0-CLOSEOUT-AND-P1-READINESS-1）

```text
P0_STATUS                       = CLOSED_PASS
PUBLIC_HTTPS_CALLBACK           = PASS（外网 400/200 可达，非 404/502/503）
COMMAND_CALLBACK_SAVE           = PASS（指令回调 URL 保存成功，suite_ticket 持续到达）
GET_VERIFY_URL                  = PASS（验签 + AES 解密 + echostr 明文返回）
SUITE_TICKET_REAL_DELIVERY      = PASS（10 分钟稳定投递，ticket_hash 前缀脱敏）
COMMAND_CALLBACK_ACK            = PASS（event_type=suite_ticket → ACK success 返回 200）
DATA_CALLBACK_SAVE              = PASS（同一物理 URL + 当前 Token/EncodingAESKey 保存成功）
SAME_PHYSICAL_CALLBACK_URL      = VALIDATED
SECRET_EXPOSURE                 = NO
DB_CHANGE                       = 0
MIGRATION                       = 0
PROBE_COMMIT                    = 7d0fe3e
FINAL_DEPLOYED_COMMIT           = ec506ef（真实回调验证时生效代码）

脱敏证据：
  - HTTP：外网 GET 400（伪造签名 fail-closed）/ 真实 verifyURL 重放 200 明文 / suite_ticket POST 200
  - 事件：event_type=suite_ticket ×3（09:07 / 09:17 / 09:27 UTC），ticket_hash 前缀 319eaae5 / 16195fe8 / 0eaf0d88
  - 时间：2026-08-20 P0 真实回调验证完成
```

安全边界：以上仅脱敏 metadata；不记录 Token / EncodingAESKey / SuiteTicket 明文 / 解密 payload。
