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

# 容器启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
