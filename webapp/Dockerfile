FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
ENV BOOK_STORE=/data BOT_MODE=paper PYTHONPATH=/app
VOLUME ["/data"]
EXPOSE 8000
# Bound to 0.0.0.0 only because the container's port is what gets published.
# Publish it to 127.0.0.1 on the host, or put an authenticating proxy in front:
#   docker run -p 127.0.0.1:8000:8000 ...
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"
CMD ["sh", "-c", "python -m uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
