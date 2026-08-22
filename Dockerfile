FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app \
    && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=120 -r requirements.txt

COPY alembic ./alembic
COPY alembic.ini .
COPY app ./app
COPY evaluation ./evaluation
COPY prompts ./prompts
COPY docker-entrypoint.sh .
COPY .env.example .env.example

RUN mkdir -p /app/data/uploads \
    && chown -R app:app /app \
    && chmod +x /app/docker-entrypoint.sh

USER app

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=3s \
    --start-period=10s \
    --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["api"]
