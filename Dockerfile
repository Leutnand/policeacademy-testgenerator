FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
RUN mkdir -p /data /app/staticfiles /app/media \
    && chown -R app:app /data /app/staticfiles /app/media

USER app
EXPOSE 8000

CMD ["sh", "/app/docker-entrypoint.sh"]