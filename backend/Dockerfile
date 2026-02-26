FROM python:3.12-slim

WORKDIR /app

# System deps: nginx, cron, pg_dump, rsync
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    cron \
    curl \
    postgresql-client \
    rsync \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY . .

# Nginx config
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Backup scripts
COPY scripts/backup.sh /app/scripts/backup.sh
COPY scripts/crontab /etc/cron.d/clearledger-cron
RUN chmod +x /app/scripts/backup.sh \
    && chmod 0644 /etc/cron.d/clearledger-cron \
    && crontab /etc/cron.d/clearledger-cron

# Volumes
VOLUME ["/data/storage", "/data/backups"]

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["/entrypoint.sh"]
