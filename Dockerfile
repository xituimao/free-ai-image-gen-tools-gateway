FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, leverage layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Unified resource directory: persisted via volume mount on cloud (-v /data/imgw:/data)
ENV STORAGE_DIR=/data
VOLUME ["/data"]
EXPOSE 8799

# Container must listen externally; forwarded-allow-ips only trusts loopback to prevent external X-Forwarded-For spoofing bypassing admin local gate.
# If there's an external reverse proxy (not 127.0.0.1), override with -e FORWARDED_ALLOW_IPS=<proxy IP>.
# For public deployment ADMIN_TOKEN must be set (-e ADMIN_TOKEN=your key), otherwise management interface has unauthorized access risk.
CMD ["sh","-c","python -m uvicorn imggen.server:app --host 0.0.0.0 --port 8799 --forwarded-allow-ips '127.0.0.1'"]
