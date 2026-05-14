# Django EV Charging Platform - Production Dockerfile
FROM python:3.12-slim

# -----------------------
# Environment Variables
# -----------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PATH="/home/appuser/.local/bin:${PATH}"

# -----------------------
# Work directory
# -----------------------
WORKDIR /app

# -----------------------
# Install system dependencies
# -----------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# -----------------------
# Create non-root user and directories
# -----------------------
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/logs /app/staticfiles && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# -----------------------
# Copy project files
# -----------------------
COPY --chown=appuser:appuser . .

# -----------------------
# Copy entrypoint and make executable
# -----------------------
COPY --chown=appuser:appuser ./entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# -----------------------
# Install Python dependencies
# -----------------------
COPY --chown=appuser:appuser requirements/prod.txt requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# -----------------------
# Verify Django installation
# -----------------------
RUN python -c "import django; print('Django version:', django.get_version())"

# -----------------------
# Expose port
# -----------------------
EXPOSE 8000

# -----------------------
# Entrypoint & CMD
# -----------------------
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "renew_website.asgi:application", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]