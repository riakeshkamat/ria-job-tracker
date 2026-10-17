FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data PRODUCTION=true
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tracker ./tracker
COPY static ./static
COPY sources.json .
CMD ["sh", "-c", "uvicorn tracker.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
