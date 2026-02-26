#!/bin/bash
# ClearLedger — ежедневный бэкап БД + файлов
# Запускается cron внутри контейнера

set -e

BACKUP_DIR="/data/backups"
DB_DIR="${BACKUP_DIR}/db"
FILES_DIR="${BACKUP_DIR}/files"
DB_NAME="${POSTGRES_DB:-clearledger}"
DB_HOST="${DB_HOST:-db}"
DB_USER="${POSTGRES_USER:-cl}"

mkdir -p "$DB_DIR" "$FILES_DIR"

DATE=$(date +%Y%m%d_%H%M)

echo "[backup] Бэкап БД: ${DB_NAME} → ${DB_DIR}/clearledger_${DATE}.sql.gz"
PGPASSWORD="${POSTGRES_PASSWORD:-clearledger}" pg_dump \
  -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" \
  | gzip > "${DB_DIR}/clearledger_${DATE}.sql.gz"

echo "[backup] Синхронизация файлов: /data/storage/ → ${FILES_DIR}/"
rsync -a --delete /data/storage/ "${FILES_DIR}/"

# Ротация: хранить 30 дневных бэкапов
echo "[backup] Ротация: удаление бэкапов старше 30 дней"
find "$DB_DIR" -name "*.sql.gz" -mtime +30 -delete

echo "[backup] Готово: $(du -sh "$DB_DIR" | cut -f1) БД, $(du -sh "$FILES_DIR" | cut -f1) файлов"
