#!/bin/bash
# Start all dev services

echo "🚀 Starting Equated development environment..."

# Start Docker services (Redis + Postgres)
echo "📦 Starting Docker services..."
docker-compose up -d redis postgres

echo "⏳ Waiting for services to be ready..."
sleep 3

# Start backend
echo "🐍 Starting backend..."
cd backend
python -m venv venv 2>/dev/null
source venv/bin/activate
pip install -r requirements.txt -q
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# Start frontend
echo "⚛️  Starting frontend..."
cd frontend
npm install -q
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ Equated is running:"
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8000"
echo "   Docs:     http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services."

trap "kill $BACKEND_PID $FRONTEND_PID; docker-compose stop redis postgres" EXIT
wait
