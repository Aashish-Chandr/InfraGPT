FROM python:3.11-slim

RUN groupadd -r operator && useradd -r -g operator operator

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=operator:operator operator.py .

USER operator

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget -qO- http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "kopf", "run", "--all-namespaces", "--liveness=http://0.0.0.0:8080/healthz", "operator.py"]
