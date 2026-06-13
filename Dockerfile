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

# 复制应用代码
COPY app/ ./app/
COPY tests/ ./tests/

# 数据目录（SQLite 持久化挂载点）
RUN mkdir -p /app/data

EXPOSE 9000

# 容器启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
