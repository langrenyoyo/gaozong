# 本地 Docker 开发说明

本文档用于 `auto_wechat` 本地开发和人工联调，不是生产部署方案。

## 1. 服务边界

| 服务 | 容器名 | 端口 | 启动入口 |
| --- | --- | --- | --- |
| AI小高线索主后端 | `auto-wechat-api-dev` | 9000 | `app.main:app` |
| 抖音AI小高客服 | `xg-douyin-ai-cs-dev` | 9100 | `apps.xg_douyin_ai_cs.main:app` |
| React 前端 | `auto-wechat-frontend-dev` | 5173 | `npm run dev` |
| 小高AI微信助手 | 不进 Docker | 19000 | Windows 宿主机单独运行 |

19000 小高AI微信助手不进入 Docker。因为它依赖 Windows 微信窗口、UIA、剪贴板、前台窗口、OCR 和本机 GUI 自动化。需要微信能力时，在 Windows 宿主机单独启动。

宿主机启动 19000：

```bash
python -m app.local_agent_main --host 127.0.0.1 --port 19000 --server-url http://127.0.0.1:9000
```

## 2. 启动和停止

一条命令构建并启动：

```bash
docker compose -f docker-compose.dev.yml up --build
```

也可以分步执行：

```bash
docker compose -f docker-compose.dev.yml build
docker compose -f docker-compose.dev.yml up
```

后台启动：

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

停止并删除容器：

```bash
docker compose -f docker-compose.dev.yml down
```

## 3. 访问地址

| 服务 | 地址 |
| --- | --- |
| 9000 API 文档 | `http://127.0.0.1:9000/docs` |
| 9100 健康检查 | `http://127.0.0.1:9100/health` |
| 9100 API 文档 | `http://127.0.0.1:9100/docs` |
| 前端 | `http://127.0.0.1:5173` |

前端访问 9000、9100、19000 使用 `127.0.0.1`，因为这些 URL 是浏览器访问宿主机端口，不是容器之间互相访问。

## 4. 健康检查

```bash
curl http://127.0.0.1:9100/health
curl http://127.0.0.1:9100/ready
curl http://127.0.0.1:9100/version
curl http://127.0.0.1:9000/docs
curl -I http://127.0.0.1:5173
```

9000 当前没有独立 `/health` 时，使用 `/docs` 验证服务存活；不要为了本地 Docker 验证新增 9000 接口。

## 5. 9100 RAG 人工检查

创建知识文档：

```bash
curl -X POST http://127.0.0.1:9100/rag/documents ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":\"demo_tenant\",\"merchant_id\":\"demo_bba\",\"douyin_account_id\":1,\"title\":\"精品BBA话术\",\"category\":\"sales_script\",\"content\":\"我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6、宝马5系、奔驰E级时，应引导客户留下联系方式。\"}"
```

训练知识库：

```bash
curl -X POST http://127.0.0.1:9100/rag/train ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":\"demo_tenant\",\"merchant_id\":\"demo_bba\",\"douyin_account_id\":1}"
```

搜索知识库：

```bash
curl -X POST http://127.0.0.1:9100/rag/search ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":\"demo_tenant\",\"merchant_id\":\"demo_bba\",\"douyin_account_id\":1,\"query\":\"客户问奥迪A6怎么回复\",\"top_k\":5}"
```

生成回复建议：

```bash
curl -X POST http://127.0.0.1:9100/douyin/conversations/1/reply-suggestion ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":\"demo_tenant\",\"merchant_id\":\"demo_bba\",\"account_id\":1,\"latest_message\":\"你们有奥迪A6吗？\"}"
```

未配置 `XG_DOUYIN_AI_LLM_API_KEY` 时，9100 `reply-suggestion` 会返回 `manual_required=true`、`llm_used=false`，不会假装智能回复成功。`auto_send` 也应保持为 `false`。

如果复用 OpenRouter 等 chat provider，建议先设置 `XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED=false`，只验证 chat 智能回复；确认 provider 支持 `/embeddings` 后，再启用真实 embedding。

Docker Compose 会从宿主机环境变量或根目录 `.env` 读取 `XG_DOUYIN_AI_LLM_*` 并透传给 9100 容器。真实 API Key 不要写进 `docker-compose.dev.yml`，也不要提交 `.env`。OpenRouter 只做 chat 联调时，建议设置 `XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED=false`。

## 6. 数据目录

`docker-data/` 是本地运行数据目录，不要提交。

常见内容：

```text
docker-data/
  auto_wechat_9000/       # 9000 本地 SQLite 数据
  xg_douyin_ai_cs/        # 9100 RAG SQLite 数据
```

该目录已由 `.gitignore` 和 `.dockerignore` 忽略。

本地联调需要基础测试数据时，手动执行：

```bash
docker compose -f docker-compose.dev.yml exec auto-wechat-api python scripts/seed_dev_data.py
```

该脚本只写本地 dev mock 数据，不会随容器启动自动执行，不会调用抖音、微信、LLM 或支付服务。

## 7. 常见问题

- 9000 没有 `/health`：使用 `http://127.0.0.1:9000/docs` 验证。
- frontend 页面访问 9000/9100 使用 `127.0.0.1`：这些地址由浏览器访问宿主机端口。
- 19000 必须宿主机运行：它依赖 Windows 微信窗口、UIA、剪贴板、前台窗口、OCR 和本机 GUI 自动化。
- `docker-data/` 不提交：这是容器运行时产生的本地数据库和 WAL 文件。
- 不要把真实 LLM API Key 写入 `docker-compose.dev.yml` 或文档；需要真实 Key 时只在本机环境变量里注入。
