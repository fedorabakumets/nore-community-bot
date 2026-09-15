FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY community_bot ./community_bot
COPY assets ./assets
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN pip install . \
    && useradd --create-home --uid 10001 botuser \
    && mkdir -p /app/data \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R botuser:botuser /app

# Stay root so a Railway volume mounted at /app/data is writable, then drop privileges.
USER root
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "community_bot.main"]
