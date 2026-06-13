FROM python:3.10-slim

WORKDIR /app

# 安装依赖（使用 Docker 专用 requirements，排除 Windows 专用包）
COPY requirements-docker.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app/ ./app/
COPY tests/ ./tests/

# 数据目录（SQLite 持久化挂载点）
RUN mkdir -p /app/data

EXPOSE 9000

# 容器启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
