FROM node:22-alpine AS build

ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}

# Бренд экосистемы-контейнера (white-label): «Экосистема <бренд>», «<бренд> Ledger».
ARG VITE_ECOSYSTEM_BRAND=ElsyPlus
ENV VITE_ECOSYSTEM_BRAND=${VITE_ECOSYSTEM_BRAND}

WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ─── runtime ─────────────────────────────────────────────────────────
FROM nginx:alpine

# Конфиг для контейнера frontend — отдаёт статику с поддержкой SPA-роутинга.
# (Контейнер nginx-router в compose стоит ПЕРЕД frontend и роутит /api/.)
RUN rm -f /etc/nginx/conf.d/default.conf
COPY <<'EOF' /etc/nginx/conf.d/default.conf
server {
    listen 80 default_server;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Хэшированные ассеты Vite — кэшировать намертво (имя меняется при пересборке).
    # Отсутствующий чанк = честный 404 (НЕ HTML-fallback: иначе браузер получает
    # text/html вместо JS → «Strict MIME type checking» на весь экран).
    location /ClearLedger/assets/ {
        alias /usr/share/nginx/html/assets/;
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }

    # index.html и SPA-fallback — всегда ревалидировать (ETag → дешёвый 304).
    # Без no-cache браузер держит старый index после деплоя и тянет удалённые
    # чанки → «Failed to fetch dynamically imported module».
    location /ClearLedger/ {
        alias /usr/share/nginx/html/;
        add_header Cache-Control "no-cache";
        try_files $uri $uri/ /index.html;
    }

    location / {
        add_header Cache-Control "no-cache";
        try_files $uri $uri/ /index.html;
    }
}
EOF

COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
