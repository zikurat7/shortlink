FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[postgres]"

RUN useradd --system --uid 10001 shortlink
USER shortlink

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')"

# Bind all interfaces so the published port is reachable from outside the container.
# Storage comes from $DATABASE_URL (PostgreSQL); without it links are kept in memory.
ENTRYPOINT ["python", "-m", "shortlink", "--host", "0.0.0.0", "--port", "8000"]
