# P1-CAR-PROJECT-DOUYIN-CS-AUTOREPLY-RAG-8788-DEPLOY-SWITCH

## 1. 目标与边界

本轮目标是把 `car-porject-main` 实际运行在 8788 的后端服务切换到已提交的新代码和正确运行态环境，使真实入口可以访问“AI 抖音客服自动回复训练”专用接口：

```text
car-porject-main 前端
-> car-porject-main 后端 8788
-> auto_wechat 9000 /knowledge-training/*
-> auto_wechat 9100
-> Milvus
```

本轮只做运行态切换和轻量验证，不触发真实业务训练，不调用 LLM，不调用抖音发送，不触发私信发送。

## 2. 旧 8788 进程定位

8788 当前不是普通 Python 宿主进程，而是 Docker/WSL 端口转发：

```text
PID 20796: wslrelay.exe
PID 18760: com.docker.backend.exe
```

进一步定位 Docker 容器：

```text
container=knowledge-train
image=car-porject-main-knowledge-train
ports=0.0.0.0:8788->8788/tcp
command=python backend/app.py
```

旧 8788 返回：

```text
GET /api/douyin-cs-autoreply/knowledge-base
status=404
```

根因：

1. 8788 运行的是旧构建镜像，未包含已提交的专用接口代码。
2. `docker-compose.yml` 未透传 `AUTO_WECHAT_KNOWLEDGE_TRAINING_*` 环境变量。

## 3. 新 8788 启动方式

本轮使用 `docker compose` 重建并替换 `knowledge-train` 容器：

```text
docker compose -f docker-compose.yml up -d --build knowledge-train
```

保留并复用：

- `knowledge-train-redis`
- `knowledge-train-qdrant`

未停止 auto_wechat 9000、auto_wechat 9100、Milvus。

## 4. 环境变量

`car-porject-main/docker-compose.yml` 新增运行态变量透传：

```text
AUTO_WECHAT_KNOWLEDGE_TRAINING_BASE_URL
AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN
AUTO_WECHAT_KNOWLEDGE_TRAINING_OPERATOR_SOURCE
AUTO_WECHAT_KNOWLEDGE_TRAINING_TIMEOUT_SECONDS
```

Docker 默认 base URL：

```text
http://host.docker.internal:9000
```

真实 token 只从 auto_wechat 9000 容器环境读取到本次 shell 进程，再注入 `knowledge-train` 容器环境；未打印、未写入 git、未写入文档。

## 5. 专用接口不再 404 验证

重建后请求：

```text
GET http://127.0.0.1:8788/api/douyin-cs-autoreply/knowledge-base
```

结果：

```text
status=200
categories_count>=1
documents_count>=1
```

结论：8788 已加载新代码并可通过 9000 代理访问统一知识库训练服务。

## 6. 8788 -> 9000 -> 9100 -> Milvus synthetic smoke

9100 容器内 Milvus collection check：

```text
backend=milvus
connected=True
collection_exists=True
schema_match=True
dimension=2048
metric_type=COSINE
```

8788 synthetic 非业务数据闭环：

```text
document_id=15
training_run_id=18
train_status=completed
chunk_count=1
error_code=None
search_hit=True
search_result_count=1
delete_ok=True
```

## 7. delete 后检索验证

删除后复查同一 synthetic 标识：

```text
search_after_delete_hit=False
cleanup_ok=True
```

结论：本轮没有遗留 synthetic 向量数据。

## 8. 页面入口轻量点验

根页面：

```text
GET http://127.0.0.1:8788/
status=200
```

根页面 HTML 未直接呈现“AI 抖音客服自动回复训练”文案，需要前端路由或页面交互进入目标模块。本轮已验证后端真实 8788 专用接口，浏览器页面完整 E2E 建议放到后续页面联调任务。

根页面静态内容轻量扫描：

```text
has_qdrant=False
has_milvus=False
has_token=False
```

## 9. 其他训练标签影响检查

本轮未修改其他训练标签业务逻辑。

已确认：

- 其他训练标签导航仍由原前端文件保留。
- 其他训练标签 API 未被本轮修改。
- Qdrant 在其他模块中的残留不作为本轮失败项。
- 本轮只要求“AI 抖音客服自动回复训练”链路使用 8788 -> 9000。

## 10. 测试结果

car-porject-main：

```text
python tests\test_douyin_cs_autoreply_9000_proxy.py -v
结果：3 tests OK

python -m py_compile backend\app.py
结果：通过

python -m unittest discover -s gold\tests -v
结果：11 tests OK

git diff --check
结果：通过
```

auto_wechat：

```text
git diff --check
结果：通过
```

## 11. 安全扫描

前端 token 扫描：

```text
rg "AUTO_WECHAT_KNOWLEDGE_TRAINING_INTERNAL_TOKEN|dev_knowledge_training_token|Authorization: Bearer" frontend
结果：未命中
```

8788 knowledge-base 响应字段名扫描未发现：

```text
qdrant
collection
vector
point
milvus
token
password
```

说明：历史 synthetic 文档标题中可能出现 `TOKEN` 测试标识，不是 internal token。

## 12. 残留风险

1. 8788 容器环境中持有 internal token，这是后端运行所需；不得把容器 inspect 输出贴到文档或日志。
2. 页面入口只做轻量检查，未执行浏览器完整 E2E。
3. 其他训练模块仍保留 Qdrant 链路，本轮明确不全局替换。

## 13. 未改内容

- 未修改 auto_wechat 业务代码。
- 未修改 car-porject-main 业务代码。
- 未修改 NewCarProject。
- 未修改自动回复 gate。
- 未新增 `/merchant/rag/*`。
- 未把 `/admin/rag/*` 作为主路径。
- 未调用 LLM。
- 未调用抖音发送上游。
- 未触发私信发送。
- 未使用真实业务知识。
- 未使用真实客户数据。
- 未提交真实 token / cookie / secret / password / Milvus URI / Qdrant URI。

## 14. 下一步任务

建议进入：

```text
P1-CAR-PROJECT-DOUYIN-CS-AUTOREPLY-RAG-PAGE-WIRE-1
```

目标：在页面层接入已验证的 8788 专用接口，完成“AI 抖音客服自动回复训练”文档管理与 search-preview 交互，不让前端持有 internal token。
