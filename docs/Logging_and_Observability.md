# Logging and observability

## Current setup

Django uses Python's standard `logging` framework with `python-json-logger` for JSON formatting; `structlog` is not installed or used. JSON Lines means one readable JSON object per line. Docker Compose mounts this directory from the project, so files survive container recreation and image rebuilds, and can be opened directly on the host in VS Code or another text editor.

- `web.jsonl` — web service logs.
- `celery-worker.jsonl` — worker logs, including task start/finish/failure events.
- `celery-beat.jsonl` — scheduled-task dispatch logs.
- `flower.jsonl` — Flower service logs.
- `charging-stations.jsonl` — charging station, station-specific and OCPP loggers.
- `inverters.jsonl` — Deye/inverter logs.

File rotation is enabled at 10 MB per file, keeping 10 rotated copies by default. The file handler uses process-safe locking because Celery's prefork workers can write concurrently. Tune this with `LOG_MAX_BYTES` and `LOG_BACKUP_COUNT`.

These files capture Python log records routed through the configured Django/Celery/Uvicorn/Flower loggers. They do not automatically include every OS, Docker daemon, PostgreSQL, Redis or Nginx message; those remain available through `docker compose logs <service>` unless separately configured for collection. Not every `print()` or third-party logger is guaranteed to enter an application file.

Task completion JSON records include `event_type`, `task_name`, `task_id`, `task_state` and `runtime_seconds`. Avoid logging passwords, API tokens, RFID credentials, or unredacted OCPP payloads.

## Inspect logs

```bash
# Follow Docker stdout logs for a service
 docker compose logs -f celery

# Follow persistent file logs
 less logs/web.jsonl
 tail -F logs/celery-worker.jsonl
 tail -F logs/charging-stations.jsonl
 tail -F logs/inverters.jsonl

# If jq is installed, filter task completions
 jq 'select(.event_type == "celery_task_finished")' logs/celery-worker.jsonl

# Produce a CSV summary grouped by Celery task
 python3 scripts/summarize_task_logs.py

# Emit the same summary as JSON
 python3 scripts/summarize_task_logs.py --format json
```

The CSV contains completed/succeeded/failed/retried counts and average, p50, p95 and maximum observed task runtime. It can be opened in a spreadsheet to compare tasks or create basic charts. It reads the active file and rotated files named `celery-worker.jsonl*`.

## Grafana dashboards

The Compose stack includes Grafana, Loki and Grafana Alloy. Alloy tails the JSONL files and sends them to Loki; Grafana has a provisioned Loki datasource and the `RENEW — System Logs & Celery` dashboard. It includes log volume/errors, Celery outcomes and p95 runtime, OCPP station activity, actual charging power, Deye telemetry runtime, PV production, battery SOC, and filtered log views. The charging-power panel remains empty until the station emits meter values; the inverter panels require Deye telemetry events. Loki and Grafana data are kept in named Docker volumes; the original text files remain under `logs/` on the host. `docker compose down` keeps these volumes; avoid `docker compose down -v` unless you intend to delete the Loki history and Grafana state.

Development access: `http://localhost:3000` (when using the local-only default, credentials are `admin` / `admin`; change the password on first login). The dashboard has a time-range picker, automatic refresh, Service and Celery task filters, log-volume graphs, task outcomes, p95 runtime, failures and recent logs. In Grafana's Explore view, users can search and sort log entries and add further LogQL filters.

For LAN access, first set a strong unique `GRAFANA_ADMIN_PASSWORD` in `.env`, then set `GRAFANA_BIND_IP` to the host's LAN IP (or `0.0.0.0` if intentionally exposing on all interfaces) and permit the port in the host firewall. Do not expose Grafana with the default local credentials. Production Compose requires `GRAFANA_ADMIN_PASSWORD` and also binds to localhost unless changed explicitly.

Grafana is its own authenticated web application, not embedded inside the Django site. Embedding it into a Django page requires a deliberate authentication/reverse-proxy design; anonymous access is disabled. The separate Grafana dashboard already provides a browser page with filters and graphs.

Logs are useful for event details and investigation. For production SLOs and reliable alerting, additionally expose counters and duration histograms to Prometheus (for example with explicit application instrumentation) and visualize those metrics in Grafana; logs and derived Loki panels are not a substitute for durable metrics.
