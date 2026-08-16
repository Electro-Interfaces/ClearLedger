# ============================================================
# ClearLedger Frontend — multi-stage build
# Stage 1: Build React SPA
# Stage 2: Serve via nginx + reverse-proxy к API
# ============================================================

# --- Stage 1: Build ---
FROM node:22-alpine AS build

WORKDIR /app

# Кешируем зависимости
COPY package.json package-lock.json ./
RUN npm ci

# Копируем исходники и билдим.
# VITE_API_URL обязателен: без него isApiEnabled() = false, и приложение
# молча собирается в офлайн-контур — работает на локальных демо-данных
# вместо API, без единого предупреждения пользователю.
ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}
ARG VITE_ECOSYSTEM_BRAND=ElsyPlus
ENV VITE_ECOSYSTEM_BRAND=${VITE_ECOSYSTEM_BRAND}
COPY . .
ENV VITE_BASE_PATH=/
RUN npm run build

# --- Stage 2: nginx ---
FROM nginx:1.27-alpine

# Копируем собранный SPA
COPY --from=build /app/dist /usr/share/nginx/html

# Копируем nginx-конфиг
COPY server/nginx/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
