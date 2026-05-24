# ClearLedger COM-Agent

HTTP-обёртка над 1С `V83.COMConnector`. Деплоится рядом с 1С на Windows
(в нашем случае `1c-dev-01.dataworker.ru`, IP 10.10.70.45).

## Зачем нужен

Backend ClearLedger (FastAPI) развёрнут на Linux в Miran (`services-01`).
Linux напрямую не может вызывать COM-объекты Windows. Этот агент решает проблему:

```
ClearLedger Backend (Linux)  ──HTTPS──▶  COM-Agent (Windows)  ──COM──▶  1С БП ГИГ
```

## API

Все endpoints возвращают JSON. Аутентификация: `Authorization: Bearer <COM_AGENT_TOKEN>`.

| Endpoint | Описание |
|----------|----------|
| `GET /health` | Без auth, статус сервиса |
| `POST /connect` | `{conn_string}` → подключение к ИБ |
| `POST /disconnect` | Закрыть соединение |
| `GET /metadata/catalogs` | Список `Catalog_*` |
| `GET /metadata/registers?name_substring=X` | Список `InformationRegister_*` |
| `POST /describe` | `{entity}` → `{dimensions, resources, attributes}` |
| `POST /fetch_entity` | `{entity, select, filter, orderby, top, skip}` → rows |
| `POST /count_entity` | `{entity, filter}` → int |
| `POST /fetch_doc_lines` | `{doc_type, doc_ref, tabular_name, select}` → ТЧ |
| `POST /fetch_postings` | `{doc_type, doc_ref}` → проводки |
| `POST /find_docs_by_nomenclature` | `{nomenclature_ref, limit}` → ПТУ |
| `POST /enrich_nomenclature` | `{refs}` → словарь с именами |

## Установка на 1c-dev-01

```powershell
# 1. Скопировать папку com-agent\ на 1c-dev-01 (через SCP или RDP)
scp -r com-agent mag@10.10.70.45:C:/Sources/

# 2. На 1c-dev-01 запустить установщик от Administrator
cd C:\Sources\com-agent
.\install-service.ps1 -Token "СЕКРЕТНЫЙ_ТОКЕН_МИНИМУМ_32_СИМВОЛА"
```

## Connect string для БП ГИГ

Файловая БД:
```
File="C:\1C\Bases\GIG";Usr="Администратор";Pwd="...";
```

Серверная (если БП на 192.168.40.31):
```
Srvr="192.168.40.31";Ref="GIG";Usr="...";Pwd="...";
```

## Управление

```powershell
Get-Service ClearLedgerCOMAgent
Stop-Service ClearLedgerCOMAgent
Start-Service ClearLedgerCOMAgent

# Логи
Get-Content C:\Services\ClearLedgerCOMAgent\agent.log -Tail 50 -Wait

# Удаление
& C:\Tools\nssm\nssm.exe remove ClearLedgerCOMAgent confirm
```

## Доступ из Miran

- `services-01` (10.10.70.51) ходит на `http://10.10.70.45:8080`
- Firewall на 1c-dev-01 открывает порт только из `10.10.70.0/24`
- Все запросы — Bearer-token аутентификация
