web: python manage.py migrate && gunicorn config.wsgi --workers 2 --threads 4 --timeout 120 --log-file -
worker: celery -A config worker --loglevel=info --pool=gevent --concurrency=20
