# P1-CAR-PROJECT-DOUYIN-CS-TRAINING-CONVERSATION-LINK-AUDIT

## 1. 目标与边界

本轮只读审计 `car-porject-main` 中“AI 抖音客服自动回复训练对话”页面链路，确认它是否是独立的训练对话链路：

```text
右侧输入客户问题
-> car-porject-main 8788 /api/douyin-cs-training/ask
-> auto_wechat 9000 /knowledge-training/ask
-> 9100 /knowledge-training/ask
-> RAG + LLM 生成建议回答
-> 左侧展示
-> 用户提交有用 / 一般 / 不准反馈
-> 反馈入库
```

边界：

- 本轮未修改 `car-porject-main` 业务代码。
- 本轮未修改 `auto_wechat` 业务代码。
- 本轮未把 `/api/douyin-cs-training/ask` 改成 `/knowledge-training/search-preview`。
- 本轮未触发抖音发送、私信发送或自动回复 gate。
- 本轮未写入真实业务知识，运行态验证仅使用 synthetic 问题。

## 2. 前端页面形态

审计路径：`E:\work\project\car-porject-main\frontend\assets\app.js`

事实：

- 页面模块 key 为 `douyin_cs_training`。
- 页面标题为“AI 抖音客服自动回复训练对话”。
- 右侧是训练问题输入区，左侧是问答历史与反馈区。
- 页面文案明确说明“项目后端会通过 auto_wechat 9000 代理到知识库训练服务；页面不传可信商户上下文”。
- 这不是单纯的检索预览页面，而是“生成建议回答 + 反馈训练”的对话形态。

右侧输入字段：

```text
merchant_id
session_key
session_title
question
prompt
douyin_account_id
use_xiaogao_knowledge_base
```

页面不会展示 Qdrant、collection、vector、Milvus 等底层字段。

## 3. 前端请求字段与响应期待

提交入口：

```text
POST /api/douyin-cs-training/ask
```

前端 payload：

```json
{
  "merchant_id": 4,
  "session_key": "",
  "session_title": "",
  "question": "...",
  "prompt": "",
  "douyin_account_id": "1",
  "use_xiaogao_knowledge_base": true
}
```

前端期望响应字段：

```text
session_key
session_title
used_knowledge_base
answer
training_id
status
knowledge_base_name
user_message_id
assistant_message_id
```

前端不会直接用 `answer` 渲染一段临时结果，而是 8788 后端先把问答落到本地 `ai_chat_messages`，再返回 `session_key`，页面刷新当前训练会话历史。

反馈入口：

```text
POST /api/douyin-cs-training/feedback
```

反馈 payload：

```json
{
  "merchant_id": 4,
  "message_id": 123,
  "rating": "useful|normal|wrong",
  "comment": "..."
}
```

反馈按钮为：

```text
有用
一般
不准
```

当前未发现独立的“修正入库”按钮；现有入库语义通过反馈提交实现，`wrong` 进入待人工复核，`useful` / `normal` 标记为已提交。

## 4. 8788 后端 ask / feedback 链路

审计路径：`E:\work\project\car-porject-main\backend\app.py`

`/api/douyin-cs-training/ask` 逻辑：

1. 禁止 `merchant` 角色使用抖音客服训练。
2. 从浏览器请求读取 `merchant_id`，调用 `can_access_merchant(conn, actor, merchant_id)` 做 car 后端权限校验。
3. 校验 `question` 非空且不超过 1000 字。
4. 校验 `prompt` 不超过 4000 字。
5. 解析 `use_xiaogao_knowledge_base`。
6. 组装发往 9000 的 payload：

```json
{
  "question": "...",
  "prompt": "...",
  "use_xiaogao_knowledge_base": true,
  "douyin_account_id": "1"
}
```

事实：

- 8788 确实转发到 `POST /knowledge-training/ask`。
- `merchant_id` 不会被转发给 9000；它只用于 8788 本地权限校验和本地会话落库。
- `tenant_id` 不会被转发给 9000。
- `douyin_account_id` 会被转发。
- `session_key` / `session_title` 不会被转发给 9000；它们只用于 8788 本地训练对话会话。
- 9000 非 2xx 或网络异常会被 8788 脱敏为：

```text
知识库训练服务暂不可用，请稍后重试
```

`/api/douyin-cs-training/feedback` 逻辑：

1. 前端提交 `message_id`、`rating`、`comment`。
2. 8788 根据 assistant message metadata 取 `training_id`。
3. 转发到：

```text
POST /knowledge-training/{training_id}/feedback
```

4. 同步写入本地 `douyin_cs_training_feedbacks`，并更新 assistant message metadata。

## 5. auto_wechat 9000 /knowledge-training/ask 契约

审计路径：

- `E:\work\project\auto_wechat\app\routers\knowledge_training.py`
- `E:\work\project\auto_wechat\app\services\xg_douyin_ai_cs_client.py`
- `E:\work\project\auto_wechat\app\config.py`

9000 已注册：

```text
POST /knowledge-training/ask
POST /knowledge-training/{training_id}/feedback
```

`/knowledge-training/ask` 请求 schema：

```text
question: 必填，1-1000 字
prompt: 可选，最多 4000 字
use_xiaogao_knowledge_base: 默认 true
douyin_account_id: 可选
```

9000 固定训练上下文：

```text
tenant_id = KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID，默认 xiaogao_system
merchant_id = KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID，默认 xiaogao_base
category_key = base，由 9100 ask 内部固定用于 RAG search
```

9000 调 9100：

```text
XgDouyinAiCsClient.knowledge_training_ask()
-> POST /knowledge-training/ask
```

返回字段白名单：

```text
training_id
question
answer
used_knowledge_base
knowledge_base_name
status
```

重要差异：

- `/knowledge-training/categories`、`/documents`、`/search-preview` 使用 `require_unified_knowledge_training_access`，支持 IP 白名单或 internal token。
- `/knowledge-training/ask` 和 `/{training_id}/feedback` 当前使用 `require_knowledge_training_ip_whitelist`，只支持 IP 白名单，不接受 internal token。

这解释了“categories/search-preview 可用，但 ask 返回 403”的现象。

## 6. 9100 /knowledge-training/ask 契约

审计路径：

- `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\routers\knowledge_training.py`
- `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\services\knowledge_training_service.py`
- `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\rag\database.py`

9100 已注册：

```text
POST /knowledge-training/ask
POST /knowledge-training/{training_id}/feedback
```

9100 ask 请求 schema：

```text
tenant_id
merchant_id
question
prompt
use_xiaogao_knowledge_base
douyin_account_id
```

9100 ask 行为：

1. 如果 `use_xiaogao_knowledge_base=true`，调用 RAG search。
2. RAG search 固定：

```text
top_k = 5
category_keys = ["base"]
tenant_id / merchant_id 来自 9000 固定封装
douyin_account_id 来自请求或默认 0
```

3. 调用 `OpenAICompatibleClient().chat(...)` 生成建议回答。
4. 如果 LLM 未配置或调用失败，会返回 fallback answer，不直接抛错。
5. 写入 `knowledge_training_sessions`：

```text
training_id
tenant_id
merchant_id
douyin_account_id
question
answer
used_knowledge_base
status
```

6. 返回：

```text
training_id
question
answer
used_knowledge_base
knowledge_base_name
status=answered
```

feedback 行为：

1. 根据 `training_id` 查 `knowledge_training_sessions`。
2. 校验 `tenant_id` / `merchant_id` 归属。
3. 写入 `knowledge_training_feedbacks`。
4. `wrong` -> `pending_review`；`useful` / `normal` -> `submitted`。

当前 feedback 不会直接把修正后的回答写入 Milvus；它只记录反馈，后续是否进入训练素材池需要单独流程承接。

## 7. 文档训练 / 检索预览 / 训练对话三条链路区分

A. 文档训练链路：

```text
/api/douyin-cs-autoreply/knowledge-base/documents/{id}/train
-> /knowledge-training/documents/{id}/train
```

用途：文档入库、chunk、embedding、Milvus upsert。

B. 检索预览链路：

```text
/api/douyin-cs-autoreply/knowledge-base/search-preview
-> /knowledge-training/search-preview
```

用途：只返回 source chunks / matches，用于确认检索效果，不生成自然语言建议回答。

C. 训练对话链路：

```text
/api/douyin-cs-training/ask
-> /knowledge-training/ask
-> /knowledge-training/ask at 9100
```

用途：右侧输入客户问题，左侧生成建议回答，再提交反馈入库。

结论：C 链路不能直接改成 B 链路。改成 search-preview 会丢失“自动生成建议回答、training_id、feedback 归属、训练对话历史”这些产品语义。

## 8. 运行态 ask 验证

执行环境：

- `car-porject-main` 容器：`knowledge-train`
- `auto_wechat` 容器：`auto-wechat-api`
- 9100 容器：`xg-douyin-ai-cs`

从 8788 容器内使用其环境变量中的 internal token 直调：

```text
POST /knowledge-training/ask
```

请求体使用 synthetic 问题，未包含真实客户数据、真实业务知识、真实凭据。

脱敏结果：

```json
{
  "status": 403,
  "error_code": "KNOWLEDGE_TRAINING_IP_FORBIDDEN",
  "has_training_id": false,
  "has_answer": false
}
```

9000 日志摘要：

```text
POST /knowledge-training/ask HTTP/1.1 403 Forbidden
```

同一日志窗口内可见：

```text
GET /knowledge-training/categories -> 9100 -> 200
POST /knowledge-training/search-preview -> 9100 -> 200
```

9100 日志：

```text
未看到对应 /knowledge-training/ask 记录
```

结论：

- 请求停在 9000 ask gate。
- 未进入 9100。
- 未触发 LLM。
- 未写入 training_id。
- 未写入训练反馈。
- 502 页面错误是 8788 对 9000 上游 403 的脱敏包装。

补充验证：

```text
POST http://127.0.0.1:8788/api/douyin-cs-training/ask
```

synthetic body 返回：

```text
status=502
has_training_id=false
has_answer=false
```

## 9. 502 根因候选

已验证根因：

```text
9000 /knowledge-training/ask 使用 IP-only gate。
8788 -> 9000 的来源 IP 是 Docker 网关地址，不在默认 IP 白名单。
虽然 8788 已带 Authorization Bearer internal token，但 ask gate 不校验 internal token。
因此 9000 返回 KNOWLEDGE_TRAINING_IP_FORBIDDEN。
8788 将该错误脱敏为 502。
```

已排除或暂未发生：

- 不是 8788 token 缺失：请求已带 Authorization Bearer。
- 不是 9000 ask route 缺失：route 已存在。
- 不是 9100 ask route 缺失：route 已存在。
- 不是 schema 422：真实返回为 403。
- 不是 9000 -> 9100 转发失败：请求未进入 9100。
- 不是 LLM provider 缺 key：本次未进入 9100，且 9100 ask 代码对 LLM 未配置有 fallback answer。
- 不是 Milvus / RAG 错误：本次未进入 9100 RAG。

## 10. 修复建议

推荐下一步最小修复任务名：

```text
P1-CAR-PROJECT-DOUYIN-CS-TRAINING-ASK-GATE-FIX-1
```

建议修复点：

1. 在 9000 `app/routers/knowledge_training.py` 中，将 `/knowledge-training/ask` 和 `/{training_id}/feedback` 的 gate 从 `require_knowledge_training_ip_whitelist` 调整为与 categories/search-preview 一致的 `require_unified_knowledge_training_access`。
2. 保持 env 级默认安全：未配置 internal token 且 IP 不命中时仍拒绝。
3. 保持 actor headers 只用于审计，不用于认证。
4. 增加测试覆盖：

```text
ask 支持 Authorization Bearer internal token
feedback 支持 Authorization Bearer internal token
token 缺失且 IP 不命中时拒绝
ask 不接受前端传入 tenant_id / merchant_id
categories/search-preview 既有行为不变
```

5. 修复后重新执行 synthetic ask，预期：

```text
status=200
has_training_id=true
has_answer=true
```

## 11. 不应改动的内容

本链路不应改成：

```text
/knowledge-training/search-preview
```

不应改动：

- 不改 `car-porject-main` 前端训练对话产品形态。
- 不改其它训练标签。
- 不改 Qdrant。
- 不改 9000 对外 schema。
- 不改自动回复真实发送 gate。
- 不触发抖音发送、私信发送。
- 不使用真实客户数据。
- 不写入真实业务知识。
- 不提交真实 token / cookie / secret / password / Milvus URI / Qdrant URI。

## 12. 下一步任务建议

进入：

```text
P1-CAR-PROJECT-DOUYIN-CS-TRAINING-ASK-GATE-FIX-1
```

目标：

```text
只修复 9000 /knowledge-training/ask 与 /knowledge-training/{training_id}/feedback 的 internal token gate，使训练对话链路继续保持 ask -> LLM 建议回答 -> feedback 入库，而不是降级为 search-preview。
```
