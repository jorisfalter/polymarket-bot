#!/bin/bash
# Deployment script for Polymarket Insider Detector
# Run on your Hetzner server

set -e

echo "🚀 Deploying Polymarket Insider Detector..."

# Update system
echo "📦 Updating system..."
apt-get update && apt-get upgrade -y

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "🐳 Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Install Docker Compose if not present
if ! command -v docker-compose &> /dev/null; then
    echo "🐳 Installing Docker Compose..."
    apt-get install -y docker-compose-plugin
fi

# Create app directory
APP_DIR="/opt/polymarket-insider"
mkdir -p $APP_DIR
cd $APP_DIR

echo "📥 Pulling latest code..."
# If using git:
# git pull origin main

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "⚠️  Creating .env file - YOU MUST EDIT THIS!"
    cat > .env << 'EOF'
# Polymarket Insider Detector Configuration
# EDIT THESE VALUES!

# Notifications - Postmark
POSTMARK_API_TOKEN=your-postmark-token
POSTMARK_FROM_EMAIL=alerts@yourdomain.com
ALERT_EMAIL=you@example.com
NOTIFICATION_MIN_SEVERITY=medium

# Optional: Webhook for n8n/Zapier
# WEBHOOK_URL=https://your-webhook-url
EOF
    echo "❌ Please edit /opt/polymarket-insider/.env with your settings"
    echo "   Then run: docker-compose up -d"
    exit 1
fi

# Build and start
echo "🔨 Building and starting containers..."
docker compose up -d --build

# Show status
echo ""
echo "✅ Deployment complete!"
echo ""
docker compose ps
echo ""
echo "📊 Dashboard: http://$(curl -s ifconfig.me):8000"
echo "📋 Logs: docker compose logs -f"

