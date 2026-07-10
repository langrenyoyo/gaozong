# ============================================================================
# ⚠️ 已废弃（DEPRECATED）— P3-PGSQL-PRECUTOVER-REMEDIATION-1 / A2
# ============================================================================
# 本文件是 SQLite-only 旧版 9000 单服务镜像，仅保留历史参考，不得用于生产。
#
# 生产 PostgreSQL 部署必须使用 Dockerfile.backend.dev（9000 + 9100 共享镜像，
# 含 apps/ / scripts/ / migrations/ + psycopg + alembic）。
#
# 本镜像与生产不兼容的点：
#   - 仅 COPY app/，不含 apps/（9100 RAG）/ scripts / migrations
#   - 数据走 SQLite 文件（/app/data），与 PG metadata 真源冲突
#   - 无 PostgreSQL 驱动，无 alembic migration 链
#
# 防误用：运行时若 APP_ENV=production，CMD 拒绝启动（倒逼改用 Dockerfile.backend.dev）。
# 保留原因：历史宝塔部署形态参考；如确认无引用可人工删除（本轮不删）。
# ============================================================================

FROM python:3.10-slim

# pip 镜像与超时配置（加速国内构建）
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 安装依赖（使用 Docker 专用 requirements，排除 Windows 专用包）
COPY requirements-docker.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# 创建非 root 运行用户，避免容器以 root 运行（安全加固）
RUN useradd -m app

# 复制应用代码（生产镜像不含测试代码，减小镜像并避免代码信息泄露）
COPY --chown=app:app app/ ./app/

# 数据目录（SQLite 持久化挂载点）
# 非 root 用户运行时需保证宿主机 ./docker-data 对 app 用户可写：
#   首次挂载空目录时 docker 继承容器内 /app/data 的 uid；
#   已存在的 root 属主目录需在宿主机 chown（见 Z5 Runbook 节 33.3 步骤 5.3）。
RUN mkdir -p /app/data && chown -R app:app /app

USER app

EXPOSE 9000

# 防误用 guard：APP_ENV=production 时拒绝启动（废弃 SQLite-only 镜像禁止生产使用）。
# 用 shell form 让 $APP_ENV 展开；exec 让 uvicorn 替换 sh 进程接管 SIGTERM。
# dev / 未设 APP_ENV 正常启动。
CMD sh -c 'if [ "$APP_ENV" = "production" ]; then echo "[DEPRECATED] SQLite-only 镜像禁止生产使用，请改用 Dockerfile.backend.dev" >&2; exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 9000'
