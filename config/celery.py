"""
Celery configuration for the Study project.

This module sets up Celery with:
- Redis as the message broker
- Gevent pool for non-blocking I/O operations
- Separate queues for heavy and light tasks
- Database connection cleanup for gevent compatibility
"""

import os
from celery import Celery
from celery.signals import task_prerun, task_postrun

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('study')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


# CRITICAL: Close database connections for gevent compatibility
# This prevents connection blocking in concurrent tasks
@task_prerun.connect
def close_db_connections_before_task(**kwargs):
    """Close all database connections before task execution"""
    from django.db import connections
    for conn in connections.all():
        conn.close_if_unusable_or_obsolete()


@task_postrun.connect
def close_db_connections_after_task(**kwargs):
    """Close all database connections after task execution"""
    from django.db import connections
    for conn in connections.all():
        conn.close()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery setup"""
    print(f'Request: {self.request!r}')
