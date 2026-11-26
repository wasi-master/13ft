# syntax=docker/dockerfile:1
FROM python:3.13.7-slim

ARG UID=1000
ARG GID=1000

RUN groupadd -g $GID thirteener && useradd -u $UID -g $GID -m thirteener

LABEL maintainer="Arian Mollik Wasi <arianmollik323@gmail.com>" \
      org.opencontainers.image.source="https://github.com/wasi-master/13ft" \
      org.opencontainers.image.version="0.3.4"

WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -U -r requirements.txt

# Copy the rest of the app (app/ and api/ end up under /app)
COPY app ./app
COPY api ./api

USER thirteener

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3)" || exit 1

WORKDIR /app/app

CMD ["python", "-m", "gunicorn", "-c", "gunicorn.conf.py", "--timeout", "120", "--threads", "8", "portable:app"]
