from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task
def sample_task():
    """
    A sample task for demonstration.
    """
    logger.info("Sample task executed successfully.")
    return "Done"
