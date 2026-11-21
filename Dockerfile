FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --gid 10001 monitor && useradd --uid 10001 --gid monitor --no-create-home monitor
COPY pyproject.toml ./
COPY constraints.txt ./
COPY src ./src
RUN PIP_CONSTRAINT=/app/constraints.txt pip install --no-cache-dir '.[api]'
COPY backend/app.py ./app.py
USER monitor
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
