#!/bin/sh
set -e

# Wait for PostgreSQL if configured
if [ -n "$DATABASE_URL" ]; then
    echo "Waiting for database..."
    # Python one-liner to check database connection
    python - <<END
import os, sys, time, urllib.parse, psycopg2

db_url = os.environ.get('DATABASE_URL')
if db_url and 'postgresql' in db_url:
    url = urllib.parse.urlparse(db_url)
    retries = 30
    while retries > 0:
        try:
            conn = psycopg2.connect(
                dbname=url.path[1:],
                user=url.username,
                password=url.password,
                host=url.hostname,
                port=url.port or 5432,
                connect_timeout=2
            )
            conn.close()
            print("PostgreSQL is ready!")
            break
        except Exception as e:
            retries -= 1
            print(f"Waiting for PostgreSQL... ({retries} left)")
            time.sleep(2)
    if retries == 0:
        print("Could not connect to PostgreSQL")
        sys.exit(1)
END
fi

# Run migrations and collect static files only on web command
if [ "$1" = "gunicorn" ]; then
    echo "Applying database migrations..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput
fi

exec "$@"
