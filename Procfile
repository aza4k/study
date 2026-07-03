web: python manage.py migrate && gunicorn config.wsgi --log-file -
worker: celery -A config worker --loglevel=info --pool=gevent --concurrency=20
