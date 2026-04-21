import re
with open("docker-compose.yml", "r", encoding="utf-8") as f:
    content = f.read()

flower_service = """
  # Celery Flower (Monitoring)
  flower:
    build: .
    container_name: renew_flower
    command: celery -A renew_website flower --port=5555
    volumes:
      - .:/app
    ports:
      - "5555:5555"
    environment:
      - DEBUG=1
      - POSTGRES_DB=${POSTGRES_DB:-renew_db}
      - POSTGRES_USER=${POSTGRES_USER:-renew_user}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-changeme}
      - POSTGRES_HOST=db
      - POSTGRES_PORT=5432
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
    depends_on:
      - db
      - redis
      - celery
"""

if "flower:" not in content:
    content = content.replace("volumes:", flower_service + "\nvolumes:")
    with open("docker-compose.yml", "w", encoding="utf-8") as f:
        f.write(content)
