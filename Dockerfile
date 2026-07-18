FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for asyncpg, Shapely, and Postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from backend directory
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend code into container workdir
COPY backend/ .

ENV PORT=8080

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
