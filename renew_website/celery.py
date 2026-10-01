import os
import logging
import logging.config
import time
from celery import Celery
from celery.signals import setup_logging, task_failure, task_postrun, task_prerun

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'renew_website.settings')

app = Celery('renew_website')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Explicitly discover tasks in the root package since it is not in INSTALLED_APPS
app.conf.imports = ('renew_website.tasks',)

logger = logging.getLogger(__name__)
_task_started_at = {}


def _configure_celery_logging(**kwargs):
    from django.conf import settings

    logging.config.dictConfig(settings.LOGGING)


def _log_task_started(sender=None, task_id=None, **kwargs):
    _task_started_at[task_id] = time.monotonic()
    logger.info(
        'Celery task started',
        extra={
            'event_type': 'celery_task_started',
            'task_name': getattr(sender, 'name', str(sender)),
            'task_id': task_id,
        },
    )


def _log_task_finished(sender=None, task_id=None, state=None, **kwargs):
    started_at = _task_started_at.pop(task_id, None)
    runtime_seconds = round(time.monotonic() - started_at, 6) if started_at is not None else None
    logger.info(
        'Celery task finished',
        extra={
            'event_type': 'celery_task_finished',
            'task_name': getattr(sender, 'name', str(sender)),
            'task_id': task_id,
            'task_state': state,
            'runtime_seconds': runtime_seconds,
        },
    )


def _log_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    logger.error(
        'Celery task failed',
        extra={
            'event_type': 'celery_task_failed',
            'task_name': getattr(sender, 'name', str(sender)),
            'task_id': task_id,
            'error_type': type(exception).__name__ if exception else None,
        },
        exc_info=(type(exception), exception, traceback) if exception else None,
    )


setup_logging.connect(_configure_celery_logging, weak=False)
task_prerun.connect(_log_task_started, weak=False)
task_postrun.connect(_log_task_finished, weak=False)
task_failure.connect(_log_task_failure, weak=False)

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')