FROM python:3.12-slim

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 统一资源目录：云上通过挂载卷持久化（-v /data/imgw:/data）
ENV STORAGE_DIR=/data
VOLUME ["/data"]
EXPOSE 8799

# 容器内必须对外监听；forwarded-allow-ips 只信任本机回环，防止外网伪造 X-Forwarded-For 绕过 admin 本机门禁。
# 如有外部反代（非 127.0.0.1），用 -e FORWARDED_ALLOW_IPS=<反代IP> 覆盖。
# 公网部署必须设置 ADMIN_TOKEN（-e ADMIN_TOKEN=你的密钥），否则管理接口存在未授权访问风险。
CMD ["sh","-c","python -m uvicorn imggen.server:app --host 0.0.0.0 --port 8799 --forwarded-allow-ips '127.0.0.1'"]
