# ─── Stage 1: Build ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ─── Stage 2: Production ──────────────────────────────────────────────────────
FROM python:3.11-slim AS production

RUN groupadd -r aiuser && useradd -r -g aiuser aiuser

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /home/aiuser/.local

COPY --chown=aiuser:aiuser data_collector.py ./
COPY --chown=aiuser:aiuser train.py ./
COPY --chown=aiuser:aiuser predict.py ./
COPY --chown=aiuser:aiuser root_cause_analyzer.py ./

# Create data directories
RUN mkdir -p /data/metrics /data/models && chown -R aiuser:aiuser /data

USER aiuser

ENV PATH=/home/aiuser/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD wget -qO- http://localhost:8080/metrics || exit 1

CMD ["python", "predict.py"]
