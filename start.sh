#!/bin/bash

# LogLibrarian Development Startup Script
# Run this from your HOST terminal (not VS Code Flatpak terminal)

set -e

echo "🚀 Starting LogLibrarian..."
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first."
    exit 1
fi

# Start services
cd "$(dirname "$0")"

echo "📦 Starting services with Docker Compose..."
docker compose up -d --build

echo ""
echo "✅ Services starting..."
echo ""
echo "Dashboard:  http://localhost:3000"
echo "Backend:    http://localhost:8000"
echo "Qdrant:     http://localhost:6333"
echo ""
echo "Run 'docker compose logs -f' to view logs"
echo "Run 'docker compose down' to stop"
