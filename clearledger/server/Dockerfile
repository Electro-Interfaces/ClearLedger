# Образ Ядра пространства — тот самый, по которому собирается боевой backend.
#
# Раньше сборка брала копию с ВМ (`/opt/build/backend.Dockerfile`), не лежавшую ни в
# одном репозитории: она молча расходилась с кодом. 31.07.2026 фронт так уехал без
# бренда — на ВМ не было нужного ARG, и build-arg ушёл в пустоту. Теперь файл
# версионируется здесь, а на ВМ его копия остаётся только как запасная.
#
# Контекст сборки — каталог `server/`.
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

# ffmpeg — сжатие видео-вложений. Запись экрана приходит в разрешении дисплея:
# двадцать мегабайт за сорок секунд, шестьдесят три за две минуты. Половину
# хранилища пространства занимали тринадцать таких файлов. После пережатия до 1600
# точек по ширине ролик весит в двадцать с лишним раз меньше, а текст интерфейса
# остаётся читаемым (13.09.2026, см. app/services/media_shrink.py).
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential curl ffmpeg     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY app ./app
CMD ["gunicorn","app.main:app","-w","2","-k","uvicorn.workers.UvicornWorker","--bind","0.0.0.0:8000","--timeout","300","--access-logfile","-"]
