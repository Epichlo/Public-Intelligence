FROM python:3.12-slim

WORKDIR /app

# Install system dependencies if needed (e.g., build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration and metadata files first for better caching
COPY pyproject.toml README.md ./

# Install project and dependencies (without installing the package in editable mode)
RUN pip install --no-cache-dir .

# Copy the source code
COPY src/ ./src

# Expose the API port
EXPOSE 8000

# Standard python environment flags
ENV PYTHONUNBUFFERED=1

# Command to run the node FastAPI app
CMD ["python", "-m", "node.main"]
