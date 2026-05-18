# =========================
# Django EV Charging Platform
# =========================
FROM python:3.12-slim

# -------------------------
# Environment variables
# -------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/appuser/.local/bin:${PATH}"

# -------------------------
# System dependencies
# -------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# -------------------------
# Create non-root user
# -------------------------
RUN useradd -m -u 1000 appuser

WORKDIR /app

# -------------------------
# Install Python deps FIRST (better caching)
# -------------------------
COPY requirements/ /app/requirements/

RUN pip install --upgrade pip && \
    pip install -r /app/requirements/prod.txt

# -------------------------
# Copy project code
# -------------------------
COPY --chown=appuser:appuser . .

# -------------------------
# Logs & static dirs
# -------------------------
RUN mkdir -p /app/logs /app/staticfiles && \
    chown -R appuser:appuser /app

# -------------------------
# Entrypoint
# -------------------------
COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER appuser

# -------------------------
# Django sanity check
# -------------------------
RUN python -c "import django; print('Django OK:', django.get_version())"

# -------------------------
# Expose port
# -------------------------
EXPOSE 8000

# -------------------------
# Run
# -------------------------
ENTRYPOINT ["/app/entrypoint.sh"]

CMD ["gunicorn", "renew_website.asgi:application", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]