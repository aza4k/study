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

# 2. Check & Generate .env file
if [ ! -f .env ]; then
    echo "[2/5] Creating .env from .env.example..."
    cp .env.example .env
    
    # Generate random 50-character SECRET_KEY
    RANDOM_KEY=$(openssl rand -base64 36 | tr -dc 'a-zA-Z0-9!@#$%^&*(-_=+)' | head -c 50)
    sed -i "s|SECRET_KEY=replace_with_a_secure_random_key_min_50_chars_for_production_2026|SECRET_KEY=$RANDOM_KEY|g" .env
    
    # Generate random DB password
    RANDOM_DB_PASS=$(openssl rand -hex 16)
    sed -i "s|study_secure_password_2026|$RANDOM_DB_PASS|g" .env
    
    echo "Generated secure SECRET_KEY and Database password in .env."
    echo "IMPORTANT: Open .env and add your GEMINI_API_KEY and domain/IP before proceeding!"
    echo "Run: nano .env"
    exit 0
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
