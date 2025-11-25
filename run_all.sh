#!/bin/zsh
echo "🚀 Starting Student Deployer Environment..."

PROJECT_ROOT=~/Developer/student-deployer
BACKEND_DIR="$PROJECT_ROOT/backend"
UI_DIR="$PROJECT_ROOT/student-ui"
POD_DIR="$PROJECT_ROOT/student_pod"

# --- Setup Docker + Minikube ---
echo "▶ Starting Docker + Minikube setup..."
open -a 'Docker Desktop'
echo '⏳ Waiting for Docker to start...'
while ! docker info >/dev/null 2>&1; do sleep 2; done
echo '✔ Docker is running'

minikube start
eval $(minikube -p minikube docker-env)
docker build -t student-web:latest $POD_DIR
echo '✅ Minikube and image setup complete'

echo ""
echo "▶ Starting Backend and Frontend..."
echo "   Backend will run on: http://127.0.0.1:8000"
echo "   Frontend will run on: http://localhost:5173"
echo ""

# Start backend in background
cd $BACKEND_DIR
source ../.venv/bin/activate
uvicorn app:app --reload --port 8000 &
BACKEND_PID=$!

# Start frontend in background
cd $UI_DIR
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅ Services started!"
echo "🔧 Backend PID: $BACKEND_PID"
echo "🎨 Frontend PID: $FRONTEND_PID"
echo ""
echo "To stop services, run:"
echo "  kill $BACKEND_PID $FRONTEND_PID"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for user interrupt
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo '\n🛑 Services stopped'; exit" INT TERM

wait
