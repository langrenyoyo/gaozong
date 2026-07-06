# P1-CAR-PROJECT-DOUYIN-CS-AUTOREPLY-RAG-9000-WIRE

## 1. 目标与边界

本轮只改 `car-porject-main` 中“AI 抖音客服自动回复训练”这一条 RAG 训练链路，使其通过 car-porject-main 后端调用 auto_wechat 9000 `/knowledge-training/*`，再由 auto_wechat 9000 -> 9100 -> Milvus 完成训练和检索。

本轮不做：

- 不全局替换所有训练标签。
- 不全局替换所有知识库训练入口。
- 不全局删除 Qdrant。
- 不删除 `backend/rag_qdrant.py`。
- 不删除 `docker-compose.yml` 中 Qdrant 服务。
- 不修改 NewCarProject。
- 不触发 LLM / 抖音发送 / 私信发送。
- 不修改自动回复 gate。
- 不新增 `/merchant/rag/*`。
- 不把 `/admin/rag/*` 作为主路径。

## 2. 范围更正

上一轮 Qdrant 审计发现 `car-porject-main` 里存在多条 Qdrant / direct_9100 旧链路。本轮只收口 `douyin_cs_training` 这一条“AI 抖音客服自动回复训练”链路。

其他模块仍保持现状：

- AI 编导训练。
- 全案策划训练。
- 账号定位训练。
- 对标账号训练。
- 通用知识库页面 `/api/knowledge-base`。

## 3. AI 抖音客服自动回复训练模块定位

前端：

- 文件：`E:\work\project\car-porject-main\frontend\assets\app.js`
- 导航项：`KNOWLEDGE_TRAIN_MODULES` 中的 `douyin_cs_training`
- 页面渲染：抖音客服训练对话工作区相关函数
- 当前 API：
  - `POST /api/douyin-cs-training/ask`
  - `POST /api/douyin-cs-training/feedback`

后端：

- 文件：`E:\work\project\car-porject-main\backend\app.py`
- 旧函数：
  - `douyin_cs_training_settings()`
  - `douyin_cs_training_request()`
- 旧行为：可配置 direct_9100 / gateway_9000，本轮已将该模块主路径改为 auto_wechat 9000。

## 4. car-porject-main 后端改造

修改文件：

- `backend/app.py`

新增能力：

- `auto_wechat_knowledge_training_settings()`
- `auto_wechat_knowledge_training_request()`
- `AutoWechatKnowledgeTrainingProxyError`
- `strip_knowledge_training_internal_fields()`

新增专用 API：

- `GET /api/douyin-cs-autoreply/knowledge-base`
- `POST /api/douyin-cs-autoreply/knowledge-base/documents`
- `PUT /api/douyin-cs-autoreply/knowledge-base/documents/{document_id}`
- `DELETE /api/douyin-cs-autoreply/knowledge-base/documents/{document_id}`
- `POST /api/douyin-cs-autoreply/knowledge-base/documents/{document_id}/train`
- `GET /api/douyin-cs-autoreply/knowledge-base/training-runs/{run_id}`
- `POST /api/douyin-cs-autoreply/knowledge-base/search-preview`

现有问答 / 反馈 API 已改为复用 9000 client：

- `POST /api/douyin-cs-training/ask`
- `POST /api/douyin-cs-training/feedback`

## 5. car-porject-main 前端改造

修改文件：

- `frontend/assets/app.js`

改造内容：

- 将导航和页面文案从“抖音客服训练”收口为“AI 抖音客服自动回复训练”。
- 移除页面文案中的“固定外部商户 / 默认 merchant_id=1”口径。
- 页面说明改为：由 car-porject-main 后端通过 auto_wechat 9000 代理到知识库训练服务。
- 错误提示收口为“知识库训练服务暂不可用，请稍后重试”。

本模块前端未持有 internal token。

## 6. Qdrant / direct_9100 在本模块的移除情况

本模块主路径：

```text
car-porject-main 前端
-> car-porject-main 后端
-> auto_wechat 9000 /knowledge-training/*
-> auto_wechat 9100
-> Milvus
```

已移除：

- `douyin_cs_training_request()` 不再拼 direct_9100 URL。
- 不再向 9100 直传 `tenant_id` / `merchant_id`。
- `douyin_cs_training_settings()` 的运行口径固定为 `auto_wechat_9000`。
- 默认 AI 配置中的 `douyin_cs_training.mode` 改为 `auto_wechat_9000`。

仍保留：

- Qdrant 代码和展示仍存在于其他训练模块和旧知识库页面。
- README 中仍有旧 Qdrant / direct_9100 说明，后续可单独清理。

## 7. auto_wechat 9000 调用方式

car-porject-main 后端调用 auto_wechat 9000 时带 headers：

```text
Authorization: Bearer <internal_token>
X-Operator-Source: car-project-main
X-Operator-Id: 当前用户 ID 或 car-project-main-system
X-Operator-Account: 当前用户账号或 car-project-main-system
X-Request-Id: car-project-main-<uuid>
```

当前 `request_actor()` 只提供用户 ID 和角色，不提供账号名。因此：

- `X-Operator-Id` 使用当前用户 ID。
- `X-Operator-Account` 暂用 `car-project-main-system` fallback。
- 后续应接入真实管理员账号上下文。

## 8. 环境变量

car-porject-main 后端新增读取：

```text
AUTO_WECHAT_KNOWLEDGE_TRAINING_BASE_URL=
AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN=
AUTO_WECHAT_KNOWLEDGE_TRAINING_OPERATOR_SOURCE=car-project-main
AUTO_WECHAT_KNOWLEDGE_TRAINING_TIMEOUT_SECONDS=30
```

安全要求：

- internal token 只允许在后端环境变量中配置。
- 不写入前端 bundle。
- 不提交真实 token。
- base URL 或 token 缺失时，前端只收到脱敏错误。

## 9. 运行态验证

本轮未执行真实 9000 -> 9100 -> Milvus synthetic 写入验证。

原因：

- 当前任务执行环境未注入真实 `AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN`。
- 按安全要求，不应使用或输出真实 token。

已通过 mock 单元测试验证：

- 9000 base URL 拼接。
- Bearer token header。
- operator headers。
- request_id。
- 去除前端传入的 `tenant_id` / `merchant_id`。
- 上游错误脱敏。
- 旧 `douyin_cs_training_request()` 不再 direct_9100。

建议用户在真实环境注入 env 后执行 synthetic smoke：

```text
GET /api/douyin-cs-autoreply/knowledge-base
POST /api/douyin-cs-autoreply/knowledge-base/documents
POST /api/douyin-cs-autoreply/knowledge-base/documents/{document_id}/train
GET /api/douyin-cs-autoreply/knowledge-base/training-runs/{run_id}
POST /api/douyin-cs-autoreply/knowledge-base/search-preview
DELETE /api/douyin-cs-autoreply/knowledge-base/documents/{document_id}
```

synthetic 文本只允许使用非业务 token，例如：

```text
SMOKE_DOUYIN_CS_AUTOREPLY_RAG_9000_TOKEN_<uuid>
```

## 10. 其他训练标签影响评估

未改：

- AI 编导训练主逻辑。
- 全案策划训练主逻辑。
- 账号定位训练主逻辑。
- 对标账号训练主逻辑。
- `/api/knowledge-base`。
- Qdrant client。
- Qdrant docker service。

## 11. 测试结果

car-porject-main：

```text
python tests\test_douyin_cs_autoreply_9000_proxy.py -v
结果：3 tests OK

python -m py_compile backend\app.py
结果：通过

python -m unittest discover -s gold\tests -v
结果：11 tests OK
```

项目根目录 `python -m unittest discover -v`：

```text
Ran 0 tests
```

原因：当前项目根目录没有标准 unittest discovery 测试包；本轮改用显式测试文件和 `gold\tests`。

前端：

```text
package.json 不存在，未执行 npm build
```

## 12. 残留风险

1. 未执行真实 9000 synthetic smoke，需要用户在真实 env 中验证。
2. `X-Operator-Account` 暂无真实管理员账号，只能 fallback。
3. README 中仍有 direct_9100 旧说明，容易误导后续部署。
4. Qdrant 仍存在于其他训练模块和旧知识库页面，这是本轮明确保留范围。
5. 页面尚未接入新增 `douyin-cs-autoreply/knowledge-base/*` 文档管理入口；本轮保留现有问答/反馈页面主交互。

## 13. 未改内容

- 未修改 auto_wechat 业务代码。
- 未修改 NewCarProject。
- 未修改自动回复 gate。
- 未删除 Qdrant。
- 未删除 `backend/rag_qdrant.py`。
- 未删除 docker-compose Qdrant service。
- 未新增 `/merchant/rag/*`。
- 未新增 `/admin/rag/*`。
- 未触发 LLM。
- 未调用抖音发送。
- 未触发私信发送。
- 未写入真实业务知识。
- 未提交真实 token / cookie / secret / password / Milvus URI / Qdrant URI。

## 14. 下一步任务

建议下一步：

```text
P1-CAR-PROJECT-DOUYIN-CS-AUTOREPLY-RAG-9000-RUNTIME-SMOKE-1
```

目标：

1. 在真实 car-porject-main 后端 env 注入 auto_wechat 9000 base URL 和 internal token。
2. 使用 synthetic 非业务文档验证 create -> train -> training-run -> search-preview -> delete。
3. 确认 search_after_delete_hit=false。
4. 确认无 token / URI / 底层向量库细节进入前端响应。
