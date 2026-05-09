# Lena Agent - Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 先复制 requirements，利用 Docker layer cache
# 依赖不变时不重新 pip install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# 非 root 用户运行（安全最佳实践：agent 进程不应有 root 权限）
RUN useradd -m -u 1000 lena \
    && mkdir -p /app/data /app/logs \
    && chown -R lena:lena /app
USER lena

CMD ["python", "-u", "-m", "src.main"]
