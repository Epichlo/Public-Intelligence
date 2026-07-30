FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies for C/Rust extensions (cryptography, zenoh)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir .

# ---------------------------------------------------------------------------

FROM python:3.12-slim

RUN groupadd --system scheduler && \
    useradd --system --gid scheduler --create-home scheduler

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

USER scheduler
WORKDIR /home/scheduler

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "scheduler.main:app", "--host", "0.0.0.0", "--port", "8000"]
