# Container image for any Docker host (Fly.io, Railway, Cloud Run, your own box).
#   docker build -t ecommerce-analytics-dashboard .
#   docker run --rm -p 8080:8080 ecommerce-analytics-dashboard   → http://localhost:8080
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# The dataset (data/Ecommerce.csv, data/ecommerce.db) ships with the image, so the
# container needs no network access and no Kaggle credentials at runtime.
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+__import__('os').environ['PORT']+'/healthz').status==200 else 1)"

CMD ["sh", "-c", "gunicorn \"app:create_app()\" --bind 0.0.0.0:${PORT} --workers 2 --timeout 60"]
