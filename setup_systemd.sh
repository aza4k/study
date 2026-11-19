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

# 3. Check .env configuration
echo "[3/6] Checking .env configuration..."
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "Please copy .env.example to .env and configure your secrets before proceeding:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
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
