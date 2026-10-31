# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build

ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}

# Бренд экосистемы-контейнера (white-label): «Экосистема <бренд>», «<бренд> Ledger».
# Пространство может жить в подкаталоге: демо-стенд отдаётся кромкой сайта
# по пути /demo-run/space/app/, снаружи он не открывается вовсе.
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
ARG VITE_ECOSYSTEM_BRAND=ElsyPlus
ENV VITE_ECOSYSTEM_BRAND=${VITE_ECOSYSTEM_BRAND}

WORKDIR /src
COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

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
RUN --mount=type=cache,target=/src/node_modules/.vite npm run build

# ─── runtime ─────────────────────────────────────────────────────────
FROM nginx:alpine

# Конфиг для контейнера frontend — отдаёт статику с поддержкой SPA-роутинга.
# (Контейнер nginx-router в compose стоит ПЕРЕД frontend и роутит /api/.)
RUN rm -f /etc/nginx/conf.d/default.conf
COPY <<'EOF' /etc/nginx/conf.d/default.conf
# Logging-only: snapshot normalized classification before SPA/internal rewrites.
# Raw request fallback also masks known prefixes when parsing fails before rewrite.
map $args $frontend_query_logged_request {
    default $request;
    ~(^|&)(code|state|access_token|refresh_token|id_token|token)= "$request_method $uri $server_protocol";
}
map $request $frontend_raw_capability_path {
    default "";
    ~*^[^\x20]+\x20(?:/|%2f)(?:a|%61)(?:p|%70)(?:i|%69)(?:/|%2f)(?:d|%64)(?:o|%6f)(?:c|%63)(?:-|%2d)(?:s|%73)(?:h|%68)(?:a|%61)(?:r|%72)(?:e|%65)(?:/|%2f) "/api/doc-share/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:a|%61)(?:p|%70)(?:i|%69)(?:/|%2f)(?:i|%69)(?:n|%6e)(?:v|%76)(?:i|%69)(?:t|%74)(?:e|%65)(?:/|%2f) "/api/invite/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:a|%61)(?:p|%70)(?:i|%69)(?:/|%2f)(?:w|%77)(?:o|%6f)(?:r|%72)(?:k|%6b)(?:/|%2f)(?:c|%63)(?:a|%61)(?:l|%6c)(?:e|%65)(?:n|%6e)(?:d|%64)(?:a|%61)(?:r|%72)(?:/|%2f)(?:f|%66)(?:e|%65)(?:e|%65)(?:d|%64)(?:/|%2f)(?!rotate(?:[?\x20]|$)) "/api/work/calendar/feed/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:a|%61)(?:p|%70)(?:i|%69)(?:/|%2f)(?:a|%61)(?:u|%75)(?:t|%74)(?:h|%68)(?:/|%2f)(?:r|%72)(?:e|%65)(?:s|%73)(?:e|%65)(?:t|%74)(?:-|%2d)(?:p|%70)(?:a|%61)(?:s|%73)(?:s|%73)(?:w|%77)(?:o|%6f)(?:r|%72)(?:d|%64)(?:/|%2f) "/api/auth/reset-password/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:a|%61)(?:p|%70)(?:i|%69)(?:/|%2f)(?:i|%69)(?:n|%6e)(?:v|%76)(?:i|%69)(?:t|%74)(?:a|%61)(?:t|%74)(?:i|%69)(?:o|%6f)(?:n|%6e)(?:s|%73)(?:/|%2f)(?:a|%61)(?:c|%63)(?:c|%63)(?:e|%65)(?:p|%70)(?:t|%74)(?:/|%2f) "/api/invitations/accept/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:a|%61)(?:p|%70)(?:i|%69)(?:/|%2f)(?:s|%73)(?:h|%68)(?:o|%6f)(?:w|%77)(?:c|%63)(?:a|%61)(?:s|%73)(?:e|%65)(?:/|%2f) "/api/showcase/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:d|%64)(?:o|%6f)(?:c|%63)(?:-|%2d)(?:s|%73)(?:h|%68)(?:a|%61)(?:r|%72)(?:e|%65)(?:/|%2f) "/doc-share/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:d|%64)(?:o|%6f)(?:c|%63)(?:-|%2d)(?:v|%76)(?:e|%65)(?:r|%72)(?:i|%69)(?:f|%66)(?:y|%79)(?:/|%2f) "/doc-verify/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:m|%6d)(?:e|%65)(?:e|%65)(?:t|%74)(?:i|%69)(?:n|%6e)(?:g|%67)(?:/|%2f) "/meeting/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:i|%69)(?:n|%6e)(?:v|%76)(?:i|%69)(?:t|%74)(?:e|%65)(?:/|%2f) "/invite/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:r|%72)(?:e|%65)(?:s|%73)(?:e|%65)(?:t|%74)(?:-|%2d)(?:p|%70)(?:a|%61)(?:s|%73)(?:s|%73)(?:w|%77)(?:o|%6f)(?:r|%72)(?:d|%64)(?:/|%2f) "/reset-password/[redacted]";
    ~*^[^\x20]+\x20(?:/|%2f)(?:s|%73)(?:h|%68)(?:o|%6f)(?:w|%77)(?:c|%63)(?:a|%61)(?:s|%73)(?:e|%65)(?:/|%2f) "/showcase/[redacted]";
}
# Нормализованный путь читается один раз на server rewrite до любого redirect/
# @public/try_files. Map без volatile хранит первоначальную classification.
# /ClearLedger/ — прежний redirect alias, его Location/URI не меняем.
map $uri $frontend_normalized_capability_path {
    default "";
    ~^/(?:ClearLedger/)?p/public\.html$ "/p/public.html";
    ~*^/(?:ClearLedger/)?api/doc-share/ "/api/doc-share/[redacted]";
    ~*^/(?:ClearLedger/)?api/invite/ "/api/invite/[redacted]";
    ~*^/(?:ClearLedger/)?api/work/calendar/feed/(?!rotate$) "/api/work/calendar/feed/[redacted]";
    ~*^/(?:ClearLedger/)?api/auth/reset-password/ "/api/auth/reset-password/[redacted]";
    ~*^/(?:ClearLedger/)?api/invitations/accept/ "/api/invitations/accept/[redacted]";
    ~*^/(?:ClearLedger/)?api/showcase/ "/api/showcase/[redacted]";
    ~*^/(?:ClearLedger/)?doc-share/ "/doc-share/[redacted]";
    ~*^/(?:ClearLedger/)?doc-verify/ "/doc-verify/[redacted]";
    ~*^/(?:ClearLedger/)?meeting/ "/meeting/[redacted]";
    ~*^/(?:ClearLedger/)?invite/ "/invite/[redacted]";
    ~*^/(?:ClearLedger/)?reset-password/ "/reset-password/[redacted]";
    ~*^/(?:ClearLedger/)?showcase/ "/showcase/[redacted]";
}
map $frontend_normalized_capability_path $frontend_capability_path {
    "" $frontend_raw_capability_path;
    default $frontend_normalized_capability_path;
}
map $frontend_capability_path $frontend_logged_request {
    "" $frontend_query_logged_request;
    default "$request_method $frontend_capability_path $server_protocol";
}
map $frontend_capability_path $frontend_capability_referrer_policy {
    "" "";
    default "no-referrer";
}
log_format frontend_safe '$remote_addr [$time_local] "$frontend_logged_request" '
                         '$status $body_bytes_sent "$http_user_agent"';
server {
    set $frontend_privacy_warmup $frontend_capability_path;
    add_header Referrer-Policy $frontend_capability_referrer_policy always;
    listen 80 default_server;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    # @public сохраняет исходные args при rewrite в /p/public.html; только
    # location callback недостаточно для защиты журнала второго nginx.
    access_log /var/log/nginx/access.log frontend_safe;

    # OAuth callback не должен оказаться в журнале второго nginx или Referer
    # чанков до загрузки React. Внешний auth gate стека остаётся обязательным.
    location = /developer/api/callback {
        access_log off;
        add_header Cache-Control "no-store" always;
        add_header Referrer-Policy "no-referrer" always;
        try_files /index.html =404;
    }

    # Хэшированные ассеты Vite — кэшировать намертво (имя меняется при пересборке).
    # Отсутствующий чанк = честный 404 (НЕ HTML-fallback: иначе браузер получает
    # text/html вместо JS → «Strict MIME type checking» на весь экран).
    location /ClearLedger/assets/ {
        alias /usr/share/nginx/html/assets/;
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header Referrer-Policy $frontend_capability_referrer_policy always;
        try_files $uri =404;
    }
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header Referrer-Policy $frontend_capability_referrer_policy always;
        try_files $uri =404;
    }

    # index.html и SPA-fallback — всегда ревалидировать (ETag → дешёвый 304).
    # Без no-cache браузер держит старый index после деплоя и тянет удалённые
    # чанки → «Failed to fetch dynamically imported module».
    location /ClearLedger/ {
        alias /usr/share/nginx/html/;
        add_header Cache-Control "no-cache";
        add_header Referrer-Policy $frontend_capability_referrer_policy always;
        try_files $uri $uri/ /index.html;
    }

    # Манифест PWA: без правильного типа Android отказывается ставить приложение
    # на домашний экран («manifest fetched with unexpected MIME type»).
    location ~* \.webmanifest$ {
        default_type application/manifest+json;
        add_header Cache-Control "no-cache";
        add_header Referrer-Policy $frontend_capability_referrer_policy always;
    }

    # Слои карты (границы регионов): без своего типа nginx отдаёт их как
    # octet-stream — мимо gzip и с no-cache от правила SPA ниже.
    location ~* \.geojson$ {
        default_type application/geo+json;
        add_header Cache-Control "public, max-age=2592000";
        add_header Referrer-Policy $frontend_capability_referrer_policy always;
    }

    location / {
        add_header Cache-Control "no-cache";
        add_header Referrer-Policy $frontend_capability_referrer_policy always;
        try_files $uri $uri/ /index.html;
    }

    gzip on;
    gzip_types application/json application/geo+json application/javascript text/css text/plain image/svg+xml;
    gzip_min_length 1024;
}
EOF

COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
