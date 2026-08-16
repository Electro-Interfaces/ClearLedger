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

# ПУСТОЙ VITE_API_URL — не «дефолт», а демо-режим: isApiEnabled() становится false,
# фронт перестаёт спрашивать сервер и показывает заглушки (пользователь Demo, компания
# «ООО ГИГ (ГазИнвестГрупп)» из config/companies.ts). В пространстве заказчика это
# выглядит как чужой бренд на его домене. Так сломался v63 (28.07.2026).
# Для контейнера значение — ORIGIN: https://<домен>. Демо-сборка возможна, но только
# осознанно: ALLOW_DEMO=1.
ARG ALLOW_DEMO=
RUN test -n "$VITE_API_URL" -o -n "$ALLOW_DEMO" || { \
      echo "ОШИБКА СБОРКИ: VITE_API_URL пуст — фронт уйдёт в демо-режим (Demo / чужая компания-заглушка)." >&2; \
      echo "Боевая сборка: --build-arg VITE_API_URL=https://<домен>" >&2; \
      echo "Демо намеренно:  --build-arg ALLOW_DEMO=1" >&2; exit 1; }

# ORIGIN, а не адрес API: путь `/api` добавляет сам клиент. С `.../api` на конце
# сборка выглядит рабочей, а логин уходит на `/api/api/auth/login` и падает в 404
# «Not Found» — так сломался v73 (28.07.2026).
RUN case "$VITE_API_URL" in */api|*/api/) \
      echo "ОШИБКА СБОРКИ: VITE_API_URL='$VITE_API_URL' оканчивается на /api." >&2; \
      echo "Нужен ORIGIN: --build-arg VITE_API_URL=https://<домен> (без /api)." >&2; exit 1;; esac
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

    location ~* \.webmanifest$ {
        default_type application/manifest+json;
        add_header Cache-Control "no-cache";
    }

    location / {
        add_header Cache-Control "no-cache";
        try_files $uri $uri/ /index.html;
    }
}
EOF

COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
