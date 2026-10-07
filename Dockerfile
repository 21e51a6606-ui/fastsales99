FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 FLASK_DEBUG=0
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend
COPY deploy/gunicorn.conf.py deploy/gunicorn.conf.py
RUN mkdir -p /app/backend/instance
VOLUME ["/app/backend/instance"]
WORKDIR /app/backend
EXPOSE 8000
CMD ["gunicorn", "--config", "/app/deploy/gunicorn.conf.py", "app:app"]
