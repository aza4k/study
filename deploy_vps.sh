#!/bin/bash
# ============================================================================
# StuDy AI - 1-Click VPS Deployment Script (Docker Compose)
# Supported OS: Ubuntu 20.04 / 22.04 / 24.04, Debian 11 / 12
# ============================================================================

set -e

echo "=========================================================="
echo "          StuDy AI - Production VPS Deployment           "
echo "=========================================================="

# 1. Check & Install Docker if missing
if ! command -v docker &> /dev/null; then
    echo "[1/5] Docker not found. Installing Docker and dependencies..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg lsb-release
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo systemctl enable docker
    sudo systemctl start docker
    echo "Docker installed successfully!"
else
    echo "[1/5] Docker is already installed."
fi

# 2. Check .env file
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "Please copy .env.example to .env and configure your secrets:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
else
    echo "[2/5] .env file detected."
fi

# 3. Build & Launch Docker containers
echo "[3/5] Building and launching containers..."
docker compose down || true
docker compose build --pull
docker compose up -d

# 4. Wait for web container to apply migrations
echo "[4/5] Waiting for services to initialize..."
sleep 10
docker compose ps

# 5. Success Message
echo "=========================================================="
echo "🎉 StuDy AI deployed successfully!"
echo "=========================================================="
echo "Useful Commands:"
echo "  - View live logs:     docker compose logs -f"
echo "  - Web service logs:   docker compose logs -f web"
echo "  - Celery logs:        docker compose logs -f celery_worker"
echo "  - Restart all:        docker compose restart"
echo "  - Stop all:           docker compose down"
echo "  - Create admin user:  docker compose exec web python manage.py createsuperuser"
echo "=========================================================="
