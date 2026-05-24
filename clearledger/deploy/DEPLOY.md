# ClearLedger Production Deployment

Структура развёртывания (Miran):

```
ledger.dataworker.ru (DNS A → 178.250.155.92)
    ↓ Nginx/HAProxy на rproxy (10.10.70.99)
    ↓ HTTPS (Let's Encrypt)
services-01:8090 (nginx-router)
    ├─ /api/* → backend (FastAPI :8000) ─→ postgres :5432
    └─ /*     → frontend (nginx + dist)
                                            ↓
                                            COM_AGENT_URL
                                            ↓
                                  1c-dev-01:8080 (Python FastAPI агент)
                                            ↓
                                            V83.COMConnector → 1С БП ГИГ
```

## Этап 1: COM-Agent на 1c-dev-01

```powershell
# На 1c-dev-01 (RDP/SSH под mag)
# 1. Скопировать папку com-agent с локальной машины
scp -i C:\Users\magsp\.ssh\mag-miran -r `
    D:\Users\magsp\Ledger\clearledger\com-agent `
    mag@10.10.70.45:C:/Sources/

# 2. На 1c-dev-01 запустить установщик (PowerShell от Admin)
cd C:\Sources\com-agent

# Сгенерировать токен (32+ символа)
$tok = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | %{[char]$_})

# Connect string — путь к БП ГИГ
$cs = 'File="C:\1C\Bases\GIG";Usr="Администратор";Pwd="";'

.\install-service.ps1 -Token $tok -AutoConnect $cs

# Сохранить токен — нужен для services-01
Write-Host "COM_AGENT_TOKEN=$tok"

# Проверка
curl http://10.10.70.45:8080/health
```

## Этап 2: PostgreSQL + Backend + Frontend на services-01

```bash
# SSH на services-01
ssh -J miran-rproxy root@10.10.70.51

# Клон репозитория
mkdir -p /data/ledger && cd /data/ledger
git clone https://github.com/Electro-Interfaces/ClearLedger.git .

# Подготовить .env (заполнить реальными значениями)
cp deploy/.env.example deploy/.env
nano deploy/.env
# Заполнить: POSTGRES_PASSWORD, JWT_SECRET, COM_AGENT_TOKEN (тот же что в агенте)

# Запуск
cd deploy
docker compose up -d --build

# Проверка
docker compose ps
curl http://10.10.70.51:8090/health
docker compose logs -f backend
```

## Этап 3: DNS-запись

Добавить A-запись на DNS-панели dataworker.ru:

```
ledger.dataworker.ru.   A   178.250.155.92
```

Проверка распространения:
```bash
dig ledger.dataworker.ru @8.8.8.8 +short    # ожидаем 178.250.155.92
```

## Этап 4: HAProxy + SSL на rproxy

```bash
# SSH на rproxy
ssh miran-rproxy

# 1. Добавить backend в /etc/haproxy/haproxy.cfg
# (вставить блок из deploy/haproxy-fragment.cfg)
nano /etc/haproxy/haproxy.cfg

# 2. Перечитать конфиг
haproxy -c -f /etc/haproxy/haproxy.cfg && systemctl reload haproxy

# 3. Получить Let's Encrypt сертификат (после DNS-распространения!)
# HAProxy уже прокси ACME на 8888, просто:
certbot certonly --standalone --preferred-challenges http \
    --http-01-port 8888 \
    -d ledger.dataworker.ru \
    --email magspb812@gmail.com \
    --agree-tos --non-interactive

# 4. Собрать .pem для HAProxy
cat /etc/letsencrypt/live/ledger.dataworker.ru/fullchain.pem \
    /etc/letsencrypt/live/ledger.dataworker.ru/privkey.pem \
    > /etc/ssl/dataworker/ledger.dataworker.ru.pem
chmod 600 /etc/ssl/dataworker/ledger.dataworker.ru.pem

# 5. Добавить bind для нового домена и use_backend ledger_backend
systemctl reload haproxy
```

## Этап 5: Smoke

```bash
# 1. Health
curl https://ledger.dataworker.ru/api/health
# {"status":"ok","version":"0.7.0","service":"ClearLedger API"}

# 2. UI в браузере
open https://ledger.dataworker.ru/ClearLedger/

# 3. Логин: admin@clearledger.ru / admin123

# 4. /1c/connection — создать подключение
#    Mode: com
#    URL: File="C:\1C\Bases\GIG";Usr="Администратор";Pwd="";
#    (этот connection_string передастся через сеть к агенту в /connect)

# 5. Запустить sync_catalogs + sync_documents
```

## Откат

```bash
# services-01: остановить stack
cd /data/ledger/deploy && docker compose down

# 1c-dev-01: остановить агента
Stop-Service ClearLedgerCOMAgent

# rproxy: убрать ledger из haproxy.cfg, перезагрузить
```
