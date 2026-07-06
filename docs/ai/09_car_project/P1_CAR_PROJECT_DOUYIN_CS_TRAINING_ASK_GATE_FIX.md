# P1-CAR-PROJECT-DOUYIN-CS-TRAINING-ASK-GATE-FIX

## 1. 目标与边界

本轮修复 `car-porject-main` 浏览器页面调用：

```text
POST /api/douyin-cs-training/ask
```

被 8788 脱敏返回“知识库训练服务暂不可用，请稍后重试”的问题。

本轮只修改 `auto_wechat` 9000 知识库训练代理 gate，不修改 `car-porject-main`，不把训练问答链路降级成 `search-preview`，不触发抖音发送、私信发送或自动回复 gate。

## 2. 根因

上一轮只读审计已确认：

```text
car-porject-main 8788 /api/douyin-cs-training/ask
-> auto_wechat 9000 /knowledge-training/ask
-> auto_wechat 9100 /knowledge-training/ask
-> RAG + LLM 建议回答
-> /knowledge-training/{training_id}/feedback
```

真实失败停在 9000 gate：

```text
9000 /knowledge-training/ask 返回 403
error_code=KNOWLEDGE_TRAINING_IP_FORBIDDEN
```

原因是 `/knowledge-training/ask` 和 `/knowledge-training/{training_id}/feedback` 仍使用 IP-only gate；而 categories、documents、search-preview 已使用统一 gate，支持：

```text
Authorization: Bearer <internal token>
X-Internal-Token
IP 白名单
```

8788 Docker 来源 IP 不在默认白名单内，即使 8788 已带 internal token，也会被旧 IP-only gate 拒绝。

## 3. 修复方案

将 9000 以下接口统一改为 `require_unified_knowledge_training_access`：

```text
POST /knowledge-training/ask
POST /knowledge-training/{training_id}/feedback
```

统一 gate 继续保持：

- 支持 internal token。
- 支持现有 IP 白名单。
- 默认空 token 安全关闭。
- operator headers 只作为审计上下文，不作为认证依据。

## 4. 修改文件

```text
app/routers/knowledge_training.py
tests/test_knowledge_training_api.py
docs/ai/09_car_project/P1_CAR_PROJECT_DOUYIN_CS_TRAINING_ASK_GATE_FIX.md
```

## 5. ask gate 修复

`/knowledge-training/ask` 现在与其它统一知识库训练接口使用一致的 trusted-source gate。

保留行为：

- 仍调用 9100 `/knowledge-training/ask`。
- 仍固定封装 `tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`。
- 仍保留 `question`、`prompt`、`douyin_account_id`、`use_xiaogao_knowledge_base`。
- 仍只返回白名单字段：`training_id`、`question`、`answer`、`used_knowledge_base`、`knowledge_base_name`、`status`。
- 未改为 `search-preview`。

## 6. feedback gate 修复

`/knowledge-training/{training_id}/feedback` 同样改为统一 trusted-source gate。

保留行为：

- 仍调用 9100 feedback 接口。
- 仍固定封装 `tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`。
- 仍保留 `rating`、`comment`。
- 仍由 9100 校验训练会话归属并写入反馈。

## 7. 测试结果

已执行：

```text
python -m pytest tests/test_knowledge_training_api.py -q
12 passed

python -m pytest tests/test_knowledge_training_unified_api.py -q
13 passed
```

测试覆盖：

- ask 支持非白名单 IP + valid internal token。
- ask 缺 token / invalid token 时 forbidden。
- ask 仍固定使用系统级 tenant / merchant。
- ask 不信任外部 `tenant_id` / `merchant_id`。
- ask 保留 question / prompt / douyin_account_id / use_xiaogao_knowledge_base。
- feedback 支持非白名单 IP + valid internal token。
- feedback 缺 token 时 forbidden。
- feedback 保留 rating / comment。
- categories / documents / search-preview 既有统一接口回归通过。

## 8. runtime smoke

本轮已重建 9000 容器：

```text
docker compose -f docker-compose.dev.yml up -d --build auto-wechat-api
```

9000 直连 smoke：

```text
source=8788_container
target=9000 /knowledge-training/ask
status=200
error_code=None
has_training_id=True
has_answer=True
```

8788 ask smoke：

```text
target=8788 /api/douyin-cs-training/ask
status=200
error_code=None
has_training_id=True
has_answer=True
has_assistant_message_id=True
```

8788 feedback smoke：

```text
target=8788 /api/douyin-cs-training/feedback
status=200
error_code=None
success=True
has_feedback=True
```

## 9. 安全确认

本轮确认：

- 未把 internal token 暴露给前端。
- 未绕过 9000。
- 未绕过 9100。
- 未关闭鉴权。
- 未硬编码 Docker 网关 IP。
- 未提交真实 token / cookie / secret / password / Milvus URI / Qdrant URI。
- 未写入真实业务知识。

## 10. 未改内容

本轮未修改：

- `car-porject-main` 前端。
- `car-porject-main` 后端。
- Qdrant。
- 其它训练标签。
- 自动回复真实发送 gate。
- 9000 对外 schema。
- 9100 业务语义。

本轮未触发：

- 抖音发送。
- 私信发送。
- 自动回复发送。
- 真实 LLM 测试。

## 11. 残留风险

运行态仍依赖：

- 8788 容器正确注入 internal token。
- 9000 容器正确注入 `KNOWLEDGE_TRAINING_INTERNAL_TOKENS`。
- 9000 指向正确 9100 base URL。
- 9100 `/knowledge-training/ask` 可用。

如果 9100 或 LLM/RAG 业务层失败，应返回业务层错误或 fallback answer，而不应再表现为 9000 gate 403。

## 12. 下一步任务

建议进入运行态 smoke：

```text
P1-CAR-PROJECT-DOUYIN-CS-TRAINING-ASK-GATE-RUNTIME-SMOKE-1
```

验证：

```text
8788 -> 9000 /knowledge-training/ask -> 9100 /knowledge-training/ask
8788 -> 9000 /knowledge-training/{training_id}/feedback -> 9100 feedback
```
