# Callback: журналы и Referrer

Authorization code по протоколу приходит в URL callback. Он не должен
сохраняться вместе со state в стандартных access logs и последующих Referrer.

Кандидат включает фильтр стандартных access records Uvicorn и Gunicorn:
query authority убирается до форматирования, сохраняются path/method/status.
Gunicorn SafeAtoms сохраняет экранирование и missing/custom-header semantics;
Authorization/Cookie/Set-Cookie atoms скрыты, Referer проверяется отдельно.
Фильтр не меняет входящий запрос, не погашает code и не заменяет OAuth policy.
Проверены пять unit случаев и настоящий локальный Uvicorn на синтетическом app.

Версионный `deploy/frontend.Dockerfile` защищает callback заголовками
`Cache-Control: no-store`, `Referrer-Policy: no-referrer`. Второй nginx
редактирует auth query также при переписывании callback в `/p/public.html`:
одного exact location недостаточно. В поставке есть отдельная проверка двух
настоящих nginx на внутренней Docker-сети с синтетическими upstream/gate.
Основное приложение и его ассеты сохраняют прежний gate.

До выпуска проверить эффективный Dockerfile и конфиги: текущий комплект
сборки фронта читает `/opt/build/frontend.Dockerfile`, а не автоматически
версионный файл. Состав кандидата должен включать проверенный конфиг и
его backup/rollback; наличие правки в Git не доказывает её попадание в образ.

Границы проверки: это стандартные access logs приложения и двух nginx.
Пользовательские log formats, error logs при upstream failure, внешний
TLS/ingress и журналы внешнего приложения требуют отдельной приёмки.
При подключении партнёра callback path и эти журналы проверяются до выдачи
рабочих разрешений. Токены и client secret в URL не передаются.
