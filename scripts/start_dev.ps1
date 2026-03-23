# Start all dev services (PowerShell)

Write-Host "🚀 Starting Equated development environment..." -ForegroundColor Cyan

# Start Docker services
Write-Host "📦 Starting Docker services..." -ForegroundColor Yellow
docker-compose up -d redis postgres

Start-Sleep -Seconds 3

# Start backend
Write-Host "🐍 Starting backend..." -ForegroundColor Green
$backend = Start-Process -PassThru -NoNewWindow powershell -ArgumentList "-Command", "cd backend; python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r requirements.txt -q; uvicorn main:app --reload --port 8000"

# Start frontend
Write-Host "⚛️  Starting frontend..." -ForegroundColor Blue
$frontend = Start-Process -PassThru -NoNewWindow powershell -ArgumentList "-Command", "cd frontend; npm install -q; npm run dev"

Write-Host ""
Write-Host "✅ Equated is running:" -ForegroundColor Green
Write-Host "   Frontend: http://localhost:3000"
Write-Host "   Backend:  http://localhost:8000"
Write-Host "   Docs:     http://localhost:8000/docs"
Write-Host ""
Write-Host "Press Ctrl+C to stop all services." -ForegroundColor Yellow

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
    docker-compose stop redis postgres
}
