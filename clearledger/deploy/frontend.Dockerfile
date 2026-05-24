FROM node:22-alpine AS build

ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}

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

    # Vite-base /ClearLedger/ — отдаём из подпапки если её просят, иначе fallback к /
    location /ClearLedger/ {
        alias /usr/share/nginx/html/;
        try_files $uri $uri/ /index.html;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
