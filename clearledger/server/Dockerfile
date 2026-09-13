FROM python:3.12-slim

# Системные зависимости: Tesseract OCR + русский язык + curl для healthcheck.
# ffmpeg — сжатие видео-вложений: запись экрана приходит в разрешении дисплея,
# двадцать мегабайт за сорок секунд; после пережатия до 1600 точек весит в
# двадцать с лишним раз меньше, текст интерфейса остаётся читаемым (13.09.2026).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-rus \
        poppler-utils \
        libglib2.0-0 \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости Python (кешируем слой)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY . .

# Директория для загрузок
RUN mkdir -p /app/uploads

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
