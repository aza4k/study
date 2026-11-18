#!/bin/bash
# ============================================================================
# StuDy AI - Native Systemd + Nginx + PostgreSQL + Redis Installer
# Supported OS: Ubuntu 20.04 / 22.04 / 24.04, Debian 11 / 12
# ============================================================================

set -e

echo "=========================================================="
echo "      StuDy AI - Native VPS Installation (Systemd)       "
echo "=========================================================="

APP_DIR="/var/www/study"

# 1. Update & Install System Dependencies
echo "[1/6] Installing system packages..."
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv \
    postgresql postgresql-contrib redis-server nginx certbot python3-certbot-nginx \
    build-essential libpq-dev curl git

# 2. Configure Redis
echo "[2/6] Enabling Redis..."
sudo systemctl enable redis-server
sudo systemctl start redis-server

# 3. Configure PostgreSQL
echo "[3/6] Setting up PostgreSQL..."
DB_NAME="study_db"
DB_USER="study_user"
DB_PASS=$(openssl rand -hex 16)

sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;" || true
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" || true
sudo -u postgres psql -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER;" || true

# 4. Copy project files to /var/www/study if running outside
if [ "$(pwd)" != "$APP_DIR" ]; then
    echo "[4/6] Setting up project directory at $APP_DIR..."
    sudo mkdir -p $APP_DIR /var/log/study
    sudo cp -r . $APP_DIR/
    sudo chown -R $USER:www-data $APP_DIR /var/log/study
fi

cd $APP_DIR

# 5. Setup Python Virtual Environment
echo "[5/6] Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create .env
if [ ! -f .env ]; then
    cp .env.example .env
    RANDOM_KEY=$(openssl rand -base64 36 | tr -dc 'a-zA-Z0-9!@#$%^&*(-_=+)' | head -c 50)
    sed -i "s|SECRET_KEY=replace_with_a_secure_random_key_min_50_chars_for_production_2026|SECRET_KEY=$RANDOM_KEY|g" .env
    sed -i "s|DATABASE_URL=postgresql://study_user:study_secure_password_2026@db:5432/study_db|DATABASE_URL=postgresql://$DB_USER:$DB_PASS@127.0.0.1:5432/$DB_NAME|g" .env
    sed -i "s|REDIS_URL=redis://redis:6379/0|REDIS_URL=redis://127.0.0.1:6379/0|g" .env
    echo "Generated .env with local PostgreSQL credentials."
fi

# Migrations & Static files
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 6. Configure Systemd & Nginx
echo "[6/6] Installing Systemd services & Nginx configuration..."
sudo cp systemd/study.service /etc/systemd/system/
sudo cp systemd/study-celery.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable study study-celery
sudo systemctl restart study study-celery

# Nginx config
sudo cp systemd/study-nginx.conf /etc/nginx/sites-available/study
sudo ln -sf /etc/nginx/sites-available/study /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "=========================================================="
echo "🎉 StuDy AI Native Installation Complete!"
echo "=========================================================="
echo "Status check:"
echo "  sudo systemctl status study"
echo "  sudo systemctl status study-celery"
echo "  sudo systemctl status nginx"
echo "To obtain free SSL (HTTPS):"
echo "  sudo certbot --nginx -d your_domain.uz"
echo "=========================================================="
