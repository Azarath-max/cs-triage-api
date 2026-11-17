FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --upgrade pip && pip install .

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Hosts such as Render inject PORT (default 10000) and expect the server to bind
# to it. Fall back to 8000 so `docker run -p 8000:8000` still works locally.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import os, sys, urllib.request; port = os.environ.get('PORT', '8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health').status == 200 else 1)"

# `exec` keeps uvicorn as PID 1 so it receives SIGTERM on redeploy or spin-down.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
