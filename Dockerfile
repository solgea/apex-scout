# Apex Scout - Production Dockerfile
# Tek image, compose ile bot + dashboard servisleri aynı image'ı kullanır.
FROM python:3.11-slim

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=UTC

WORKDIR /app

# System dependencies
# curl: healthcheck için gerekli
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (cache layer)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Uygulama kodu
COPY . .

# Veri/log dizinleri (non-root kullanıcıya ait)
RUN mkdir -p /app/data /app/logs /app/data/recovery && \
    useradd -m -u 1000 apex && \
    chown -R apex:apex /app

USER apex

# Expose
EXPOSE 8501

# Default: bot modu (compose dashboard servisi override eder)
CMD ["python", "main.py"]
