# Use Python slim image (smaller base)
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies (minimal for OpenCV headless)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy requirements first (Docker layer caching)
COPY requirements.txt .

# Install Python dependencies with optimizations
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Expose port
EXPOSE 8000

# Production finance cutover is explicit in the immutable release artifact.
# Startup still fails closed unless the PostgreSQL schema and one-way durable
# authority latch pass scripts/activate_canonical_finance.py.
ENV CANONICAL_FINANCE_ACTIVATE=1 \
    CANONICAL_FINANCE_API_ENABLED=1 \
    CANONICAL_FINANCE_READS_ENABLED=1 \
    CANONICAL_FINANCE_WRITES_ENABLED=1 \
    CANONICAL_FINANCE_LATCH_ENFORCED=1 \
    PROJECT_DOCUMENT_WRITES_ENABLED=1 \
    DASHBOARD_ACTOR_ASSERTION_REQUIRED=1

# Health check fails on HTTP errors and on a malformed/unhealthy JSON contract.
HEALTHCHECK --interval=30s --timeout=30s --start-period=10s --retries=5 \
    CMD python -c "import requests; response=requests.get('http://localhost:8000/health',timeout=10); response.raise_for_status(); payload=response.json(); assert payload.get('status') in {'healthy','degraded'}" || exit 1

# Run with optimized gunicorn settings (Increased threads for IO-bound work)
CMD ["sh", "-c", "python scripts/activate_canonical_finance.py && exec gunicorn main:app -c gunicorn.conf.py --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - --log-level info"]
