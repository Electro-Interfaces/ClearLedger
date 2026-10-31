# Новый проверенный статический пакет; прежний runtime и хешированные ассеты
# сохраняются для уже открытых вкладок до их штатного обновления.
FROM ledger-frontend-gig:v426 AS files
FROM elsyplus/ledger-frontend-gig:v421
COPY --from=files /usr/share/nginx/html/ /usr/share/nginx/html/
