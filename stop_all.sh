#!/bin/zsh
echo "🛑 Stopping all services..."

# Stop backend
echo "Stopping backend (uvicorn)..."
pkill -f "uvicorn app:app"

# Stop frontend
echo "Stopping frontend (vite)..."
pkill -f "vite"

# Stop any port-forwards
echo "Stopping port-forwards..."
pkill -f "kubectl port-forward"

echo ""
echo "✅ All services stopped!"
echo ""
echo "Verify with:"
echo "  lsof -i:8000  # backend"
echo "  lsof -i:5173  # frontend"
