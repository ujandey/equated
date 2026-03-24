# 🎓 Equated — AI STEM Learning Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/Node.js-18+-green.svg)](https://nodejs.org/)
[![Built with FastAPI](https://img.shields.io/badge/FastAPI-0.109+-purple.svg)](https://fastapi.tiangolo.com/)
[![Built with Next.js](https://img.shields.io/badge/Next.js-14+-black.svg)](https://nextjs.org/)

> **Multi-engine AI platform for STEM education** that solves mathematical and scientific problems with step-by-step explanations, solution verification, and intelligent model routing for optimal cost efficiency.

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Running the Project](#running-the-project)
- [Environment Configuration](#environment-configuration)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [API Documentation](#api-documentation)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Support](#support)

---

## 🎯 Overview

**Equated** is an AI-powered STEM learning platform designed for school and engineering students. Unlike generic AI chatbots, Equated is purpose-built to:

- ✅ Solve complex STEM problems step-by-step with structured explanations
- ✅ Verify solutions using a dedicated symbolic math engine (SymPy)
- ✅ Route problems to the most cost-effective AI model (DeepSeek, Groq, Claude, GPT-4)
- ✅ Cache solutions using vector similarity search to reduce redundant API calls
- ✅ Support multiple input formats (text, LaTeX, images via OCR, documents)
- ✅ Maintain conversation context for follow-up questions
- ✅ Track user credits and monetize through sustainable pricing

The platform is built to be **production-grade from day one**, with comprehensive monitoring, error tracking, and analytics.

---

## ✨ Features

### Core Capabilities
- **Multi-Format Problem Input**: Accept typed questions, LaTeX expressions, images (OCR), and uploaded documents
- **Intelligent Model Routing**: Automatically select the most cost-effective AI model based on problem complexity
- **Step-by-Step Solutions**: Provide structured explanations with problem interpretation, concepts, steps, and summary
- **Solution Verification**: Verify all answers using symbolic math before returning to users
- **Vector Caching**: 30-60% cost reduction through semantic question caching
- **Conversation Context**: Maintain session context for multi-turn interactions
- **Math Engine**: SymPy-powered symbolic computation (algebra, calculus, matrices, equation solving)
- **OCR & Parsing**: Convert images to text/LaTeX automatically
- **analytics**: Track user behavior, model accuracy, cache hit rates, and cost-per-solve

### Business Features
- **Credit-Based System**: Free tier (5-7 solves/day) + paid packages (₹10/30 solves)
- **Ad Integration**: Non-intrusive banner ads to subsidize free tier
- **Payment Processing**: Razorpay integration for secure transactions
- **Usage Monitoring**: Real-time analytics and error tracking via PostHog & Sentry

---

## 🏗️ Architecture

### High-Level System Design

```
┌─────────────────────────────────────────────────────────────┐
│                     Student Browser                         │
│                    (Next.js Frontend)                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Vercel (Deployment)                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   Next.js 14 + App Router + Server Components       │   │
│  │   - Authentication (Supabase Auth)                  │   │
│  │   - API Gateway (Next.js API Routes)                 │   │
│  │   - Model Router (Problem Classification)           │   │
│  │   - UI (Tailwind + shadcn/ui + KaTeX)              │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────┬──────────────────────────────────────────────┘
              │
              ├─────────────────────┬──────────────────────┐
              │                     │                      │
              ▼                     ▼                      ▼
    ┌──────────────────┐  ┌─────────────────┐  ┌───────────────────┐
    │  Render.com      │  │  Supabase       │  │  Cloud APIs       │
    │                  │  │                 │  │                   │
    │ FastAPI Backend  │  │ - PostgreSQL    │  │ - DeepSeek API    │
    │ - AI Router      │  │ - Auth          │  │ - Groq API        │
    │ - Math Engine    │  │ - Storage       │  │ - OpenAI/Claude   │
    │ - Verification   │  │ - Embeddings    │  │ - Embeddings      │
    │ - OCR/Parser     │  │ - pgvector      │  │                   │
    │ - Celery Workers │  │ - Redis Store   │  └───────────────────┘
    │                  │  │                 │
    └──────────────────┘  └─────────────────┘
```

### Data Flow: Problem-Solving Pipeline

```
User Input (text/image/LaTeX)
         │
         ▼
Problem Parser (OCR, LaTeX → text)
         │
         ▼
Vector Similarity Search (pgvector)
    ├─ HIT  → Return Cached Solution ──┐
    └─ MISS → Continue                 │
             │                         │
             ▼                         │
    AI Model Router                    │
    (Classify by complexity)           │
    ├─ Low  → Groq (free)              │
    ├─ High → DeepSeek R1 (~$0.001)    │
    └─ Math → SymPy directly           │
             │                         │
             ▼                         │
    LLM generates solution              │
             │                         │
             ▼                         │
    Math Engine Verification            │
             │                         │
             ▼                         │
    Structured Explanation              │
             │                         │
             ▼                         │
    Cache Solution                      │
             │                         │
             └─────────────────────────►
                                       │
                                       ▼
                            Return to Student
```

---

## 🧪 Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Next.js 14, React 18, TypeScript | Web interface with server-side rendering |
| **Styling** | Tailwind CSS, PostCSS, shadcn/ui | Design system and UI components |
| **Math Rendering** | KaTeX, react-katex | Fast LaTeX math rendering |
| **Backend** | Python 3.11+, FastAPI, Uvicorn | REST API and business logic |
| **AI Models** | DeepSeek R1/V3, Groq (Llama 3.3 70B), OpenAI | Multi-model LLM routing |
| **Math Engine** | SymPy | Symbolic computation & verification |
| **OCR** | Tesseract, pix2tex, Pillow | Image → text/LaTeX conversion |
| **Database** | PostgreSQL 16 (Supabase), pgvector | Relational data + vector embeddings |
| **Cache** | Redis | Session cache, rate limiting, queue |
| **Vector Storage** | pgvector (Supabase) | Semantic similarity search |
| **Auth** | Supabase Auth, PyJWT | Email/OAuth, JWT token validation |
| **Payments** | Razorpay | Credit system transactions |
| **File Storage** | Supabase Storage | Document uploads |
| **Background Jobs** | Celery + Redis | Async task processing |
| **Monitoring** | PostHog, Sentry | Analytics, error tracking |
| **Containerization** | Docker, Docker Compose | Development & production deployment |

---

## 📋 Prerequisites

Before cloning and setting up the project, ensure you have the following installed:

### System Requirements
- **OS**: Windows, macOS, or Linux
- **RAM**: 4 GB minimum (8 GB recommended)
- **Disk Space**: 5 GB minimum

### Required Software

#### For Full Stack Development
- **Git** (v2.30+): [Download Git](https://git-scm.com/)
- **Docker Desktop** (v20.10+): [Download Docker](https://www.docker.com/products/docker-desktop)
- **Docker Compose** (v2.0+): Usually bundled with Docker Desktop

#### For Backend Development Only
- **Python** (v3.11 or higher): [Download Python](https://www.python.org/downloads/)
  - Verify: `python --version`
- **pip** (package manager, comes with Python)
- **virtualenv** or `venv` (for isolated Python environments)

#### For Frontend Development Only
- **Node.js** (v18 or higher): [Download Node.js](https://nodejs.org/)
  - Verify: `node --version`
- **npm** (v9 or higher, comes with Node.js)
  - Verify: `npm --version`

#### Optional (for local database & cache)
- **PostgreSQL** (v14+): [Download PostgreSQL](https://www.postgresql.org/download/)
- **Redis** (v7+): [Download Redis](https://redis.io/download)

### API Keys & External Services

You'll need to create accounts and obtain API keys for:

1. **DeepSeek API**: [https://platform.deepseek.com](https://platform.deepseek.com)
   - For multi-engine AI routing
   
2. **Groq API**: [https://groq.com](https://groq.com)
   - For free tier high-speed inference
   
3. **Supabase**: [https://supabase.com](https://supabase.com)
   - PostgreSQL database, vector storage, authentication
   
4. **Razorpay** (optional, for payments): [https://razorpay.com](https://razorpay.com)
   
5. **PostHog** (optional, for analytics): [https://posthog.com](https://posthog.com)
   
6. **Sentry** (optional, for error tracking): [https://sentry.io](https://sentry.io)

---

## 🚀 Installation & Setup

### Step 1: Clone the Repository

#### Via HTTPS (Recommended for most users)
```bash
git clone https://github.com/your-username/equated.git
cd equated
```

#### Via SSH (If you've set up SSH keys)
```bash
git clone git@github.com:your-username/equated.git
cd equated
```

#### Via GitHub CLI
```bash
gh repo clone your-username/equated
cd equated
```

#### Verify Cloning
```bash
# Check repository structure
ls -la
# or on Windows PowerShell:
Get-ChildItem -Force
```

Expected output should show:
```
docker-compose.yml
README.md
PRD.txt
TechStack.txt
system_architecture.md
ai/
backend/
frontend/
database/
scripts/
infra/
```

---

### Step 2: Environment Setup

#### A. Copy Environment Files

Copy the example environment files to create local `.env` files:

```bash
# Backend environment
cd backend
copy .env.example .env
cd ..

# Frontend environment
cd frontend
copy .env.example .env
cd ..

# Root environment (if exists)
copy .env.example .env
```

On Linux/macOS, replace `copy` with `cp`.

#### B. Configure Environment Variables

**Backend** (backend/.env):
```bash
# FastAPI Configuration
DEBUG=True
WORKERS=1

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/equated
REDIS_URL=redis://localhost:6379/0

# AI Models
DEEPSEEK_API_KEY=your_deepseek_key_here
GROQ_API_KEY=your_groq_key_here
OPENAI_API_KEY=your_openai_key_here

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your_supabase_publishable_key_here
SUPABASE_SECRET_KEY=your_secret_key_here

# JWT verification is automatic via JWKS — no secret key needed
JWT_EXPIRATION_HOURS=24

# Razorpay (optional)
RAZORPAY_KEY_ID=your_key_id
RAZORPAY_KEY_SECRET=your_key_secret

# Sentry (optional)
SENTRY_DSN=your_sentry_dsn

# Environment
ENVIRONMENT=development
```

**Frontend** (frontend/.env.local):
```bash
# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your_supabase_publishable_key_here

# Backend API
NEXT_PUBLIC_API_URL=http://localhost:8000

# PostHog Analytics (optional)
NEXT_PUBLIC_POSTHOG_KEY=your_posthog_key
NEXT_PUBLIC_POSTHOG_HOST=https://app.posthog.com

# Sentry (optional)
NEXT_PUBLIC_SENTRY_DSN=your_sentry_dsn

# Environment
NEXT_PUBLIC_ENVIRONMENT=development
```

---

### Step 3: Choose Your Setup Method

Choose one of the following based on your preference:

#### Option A: Docker Compose (Recommended for Full Stack)

**Fastest setup** — runs all services (Frontend, Backend, PostgreSQL, Redis) in isolated containers.

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Stop all services
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

**Accessing services:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Redis: localhost:6379
- PostgreSQL: localhost:5432

---

#### Option B: Manual Setup (Backend Only)

**Better for backend-focused development** — requires manual database/Redis setup.

##### 1. Start PostgreSQL & Redis

If you have them installed locally:
```bash
# PostgreSQL (keep running in background)
pg_ctl start

# Redis (keep running in another terminal)
redis-server
```

Or use Docker for these services only:
```bash
docker-compose up -d postgres redis
```

##### 2. Set Up Backend

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize database migrations
alembic upgrade head

# Start FastAPI server
uvicorn main:app --reload --port 8000
```

Backend is now running at: **http://localhost:8000**  
API documentation: **http://localhost:8000/docs**

---

#### Option C: Manual Setup (Frontend Only)

**Good for UI/UX development** — requires backend to run separately.

```bash
cd frontend

# Install Node dependencies
npm install
# or if you prefer yarn:
yarn install

# Start development server
npm run dev
# or with yarn:
yarn dev
```

Frontend is now running at: **http://localhost:3000**

---

### Step 4: Initialize Database

```bash
cd backend

# Run migrations
alembic upgrade head

# Seed sample data (optional)
python check_db.py
```

---

## 🏃 Running the Project

### Using Docker Compose (Full Stack)

```bash
# From project root
docker-compose up -d

# View logs in real-time
docker-compose logs -f

# Access services:
# - Frontend: http://localhost:3000
# - Backend API: http://localhost:8000
# - API Docs: http://localhost:8000/docs
```

### Manual Backend + Manual Frontend

**Terminal 1 - Backend:**
```bash
cd backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
uvicorn main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

**Terminal 3 - Celery Workers (optional, for background jobs):**
```bash
cd backend
celery -A workers.ai_queue worker --loglevel=info
```

---

## 🔧 Environment Configuration

### Backend Configuration Details

The backend uses environment variables for configuration. Key areas:

#### AI Model Selection
Located in `backend/ai/router.py`, the router automatically selects models based on:
- Problem complexity (low/high)
- Problem type (math, physics, general)
- Cost considerations

#### Cache Configuration
- Vector similarity threshold: `0.85` (highly similar questions)
- Cache TTL: `604800` seconds (7 days)
- Enable/disable via `ENABLE_CACHE=True/False`

#### Rate Limiting
Defined in `backend/services/rate_limiter.py`:
- Free tier: 5-7 solves/day
- Premium tiers: unlimited

### Frontend Configuration Details

The frontend uses Next.js environment variables prefixed with `NEXT_PUBLIC_` for client-side access.

Key configurations:
- **Server-side API**: Uses `process.env.NEXT_PUBLIC_API_URL`
- **Supabase**: Real-time auth and database sync
- **Analytics**: PostHog tracks user behavior

---

## 📁 Project Structure

```
equated/
├── README.md                 # This file
├── docker-compose.yml        # Docker orchestration for full stack
├── PRD.txt                   # Product Requirements Document
├── TechStack.txt             # Technology stack documentation
├── system_architecture.md    # System design & data flow
│
├── backend/                  # Python FastAPI Backend
│   ├── main.py              # FastAPI app entry point
│   ├── requirements.txt      # Python dependencies
│   ├── Dockerfile           # Backend container definition
│   ├── .env.example         # Example environment variables
│   │
│   ├── ai/                  # AI & ML modules
│   │   ├── router.py        # Model selection logic
│   │   ├── classifier.py    # Problem classification
│   │   ├── prompt_optimizer.py # Prompt engineering
│   │   ├── cost_optimizer.py   # Cost tracking
│   │   ├── fallback.py      # Fallback strategies
│   │   ├── models.py        # AI model definitions
│   │   ├── prompts.py       # System prompts
│   │   └── cost_matrix.json # Model pricing data
│   │
│   ├── db/                  # Database layer
│   │   ├── connection.py    # Database connection pooling
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   └── schema.py        # Database schema definitions
│   │
│   ├── services/            # Business logic services
│   │   ├── math_engine.py       # SymPy math computation
│   │   ├── explanation.py       # Solution explanation generation
│   │   ├── input_validator.py   # Input validation & normalization
│   │   ├── auth.py              # Authentication logic
│   │   ├── credits.py           # Credit system management
│   │   ├── parser.py            # Problem parsing
│   │   ├── query_normalizer.py  # Query normalization
│   │   ├── verification.py      # Solution verification
│   │   ├── streaming_service.py # Real-time streaming
│   │   └── rate_limiter.py      # Rate limiting
│   │
│   ├── routers/             # API endpoint definitions
│   │   ├── chat.py          # Chat/solve endpoints
│   │   ├── auth.py          # Authentication endpoints
│   │   ├── credits.py       # Credit system endpoints
│   │   ├── ads.py           # Ad serving endpoints
│   │   ├── analytics.py     # Analytics endpoints
│   │   ├── health.py        # Health check endpoints
│   │   └── admin.py         # Admin panel endpoints
│   │
│   ├── cache/               # Caching mechanisms
│   │   ├── query_cache.py       # Question similarity cache
│   │   ├── embeddings.py        # Embedding generation
│   │   ├── redis_cache.py       # Redis operations
│   │   ├── vector_cache.py      # Vector storage interface
│   │   └── cache_metrics.py     # Cache performance metrics
│   │
│   ├── workers/             # Celery background jobs
│   │   ├── tasks.py         # Task definitions
│   │   ├── ai_queue.py      # AI processing queue
│   │   ├── queue.py         # General queue management
│   │   └── worker.py        # Worker configuration
│   │
│   ├── gateway/             # API gateway middleware
│   │   ├── auth_middleware.py   # Authentication checks
│   │   ├── rate_limit.py        # Rate limiting middleware
│   │   └── request_logger.py    # Request logging
│   │
│   ├── monitoring/          # Observability & monitoring
│   │   ├── logging.py       # Structured logging
│   │   ├── metrics.py       # Prometheus metrics
│   │   ├── tracing.py       # Distributed tracing
│   │   └── json_logger.py   # JSON log formatting
│   │
│   ├── core/                # Core utilities
│   │   ├── exceptions.py    # Custom exceptions
│   │   └── dependencies.py  # FastAPI dependency injection
│   │
│   ├── config/              # Configuration management
│   │   ├── settings.py      # Main settings
│   │   └── feature_flags.py # Feature toggles
│   │
│   ├── alembic/             # Database migrations
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/        # Migration scripts
│   │
│   └── tests/               # Backend tests
│       ├── test_math_engine.py
│       ├── test_router.py
│       └── ...
│
├── frontend/                # Next.js Frontend
│   ├── package.json         # Node.js dependencies
│   ├── next.config.js       # Next.js configuration
│   ├── tsconfig.json        # TypeScript configuration
│   ├── tailwind.config.js   # Tailwind CSS configuration
│   ├── postcss.config.js    # PostCSS configuration
│   ├── Dockerfile           # Frontend container definition
│   ├── .env.example         # Example environment variables
│   │
│   ├── src/
│   │   ├── app/             # Next.js App Router
│   │   │   ├── layout.tsx   # Root layout
│   │   │   ├── page.tsx     # Home page
│   │   │   ├── solve/       # Problem solver page
│   │   │   ├── dashboard/   # User dashboard
│   │   │   └── ...
│   │   │
│   │   ├── components/      # Reusable React components
│   │   │   ├── ProblemSolver.tsx
│   │   │   ├── SolutionDisplay.tsx
│   │   │   ├── MathRenderer.tsx
│   │   │   └── ...
│   │   │
│   │   ├── hooks/           # Custom React hooks
│   │   │   ├── useSolver.ts
│   │   │   ├── useAuth.ts
│   │   │   └── ...
│   │   │
│   │   ├── lib/             # Utility functions
│   │   │   ├── api.ts       # API client
│   │   │   ├── supabase.ts  # Supabase client
│   │   │   └── ...
│   │   │
│   │   ├── store/           # State management (Zustand)
│   │   ├── types/           # TypeScript type definitions
│   │   └── styles/          # Global styles
│   │
│   └── public/              # Static assets
│       └── ...
│
├── database/                # Database scripts & migrations
│   ├── schema.sql           # Database schema definition
│   ├── seed.sql             # Sample data
│   └── migrations/          # SQL migration files
│       └── 001_initial.sql
│
├── ai/                      # AI configuration & docs
│   ├── cost_matrix.json     # Model pricing
│   ├── model_config.json    # Model configurations
│   └── router_logic.md      # AI routing documentation
│
├── database/                # Database migrations & setup
│   └── schema.sql
│
├── scripts/                 # Utility scripts
│   ├── db_migrate.sh        # Database migration script
│   ├── start_dev.sh         # Development start script
│   └── start_dev.ps1        # PowerShell dev start
│
├── infra/                   # Infrastructure configuration
│   ├── docker/              # Docker configurations
│   ├── nginx/               # Nginx reverse proxy
│   ├── ci/                  # CI/CD configurations
│   └── env/                 # Environment-specific config
│
└── .gitignore               # Git ignore rules
```

---

## 👨‍💻 Development Workflow

### Backend Development

#### Hot Reload During Development
```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

The `--reload` flag automatically restarts the server when you modify Python files.

#### Running Tests
```bash
cd backend
pytest tests/ -v

# Run specific test file
pytest tests/test_math_engine.py -v

# Run with coverage
pytest --cov=backend tests/
```

#### Database Migrations
```bash
cd backend

# Create a new migration
alembic revision --autogenerate -m "Add new column"

# Review generated migration in alembic/versions/

# Apply migrations
alembic upgrade head

# Roll back last migration
alembic downgrade -1
```

#### Running Background Workers
```bash
cd backend

# In one terminal, start Redis (if not already running):
redis-server

# In another terminal, start Celery worker:
celery -A workers.ai_queue worker --loglevel=info

# Monitor tasks:
celery -A workers.ai_queue events
```

### Frontend Development

#### Hot Module Replacement (HMR)
```bash
cd frontend
npm run dev
```

Next.js automatically reloads changes in the browser.

#### Building for Production
```bash
cd frontend
npm run build
npm start
```

#### Linting & Code Quality
```bash
cd frontend
npm run lint
```

### Adding New Features

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** in the appropriate module

3. **Test your changes**:
   ```bash
   # Backend
   cd backend && pytest tests/

   # Frontend
   cd frontend && npm run lint
   ```

4. **Commit with clear messages**:
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

5. **Push and create a Pull Request**:
   ```bash
   git push origin feature/your-feature-name
   ```

---

## 📚 API Documentation

### Interactive API Docs

Once the backend is running, visit:

```
http://localhost:8000/docs
```

This provides an interactive Swagger UI where you can test all endpoints.

### Key API Endpoints

#### Authentication
- `POST /api/auth/register` — Register new user
- `POST /api/auth/login` — Login user
- `POST /api/auth/logout` — Logout user
- `GET /api/auth/me` — Get current user info

#### Problem Solving
- `POST /api/solve` — Submit problem for solving
- `GET /api/solve/{problem_id}` — Get solution details
- `GET /api/solve/history` — Get user's solve history

#### Credits
- `GET /api/credits/balance` — Get current credit balance
- `POST /api/credits/purchase` — Purchase credit packages
- `GET /api/credits/history` — Get credit transaction history

#### Analytics
- `GET /api/analytics/usage` — Get usage statistics
- `GET /api/analytics/topics` — Get topic trends

### Example API Call

```bash
# Solve a math problem
curl -X POST http://localhost:8000/api/solve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "problem": "Solve 2x + 5 = 13",
    "subject": "math"
  }'
```

---

## 🚢 Deployment

### Frontend Deployment (Vercel)

1. **Push code to GitHub**:
   ```bash
   git add .
   git commit -m "Deploy to production"
   git push origin main
   ```

2. **Connect GitHub to Vercel**:
   - Go to [vercel.com](https://vercel.com)
   - Click "New Project"
   - Import your GitHub repository
   - Set environment variables in Vercel dashboard

3. **Automatic deployments**:
   - Every push to `main` triggers production deployment
   - Every PR creates a preview deployment

### Backend Deployment (Render)

1. **Create Render account** at [render.com](https://render.com)

2. **Connect GitHub repository**:
   - Create new "Web Service"
   - Connect GitHub repo
   - Set root directory to `backend/`
   - Set build command: `pip install -r requirements.txt`
   - Set start command: `uvicorn main:app --host 0.0.0.0`
   - Add environment variables

3. **Add database**:
   - Create PostgreSQL database on Render
   - Update `DATABASE_URL` in service environment

### Database Deployment (Supabase)

1. **Create Supabase project** at [supabase.com](https://supabase.com)

2. **Get connection strings**:
   - Project Settings → Database → Connection Strings
   - Use PostgreSQL connection string in backend

3. **Run migrations**:
   ```bash
   alembic upgrade head
   ```

---

## 🤝 Contributing

We welcome contributions! Here's how to get started:

### Code of Conduct
- Be respectful and inclusive
- Report issues constructively
- Collaborate openly

### Contribution Guidelines

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit changes**: `git commit -m 'Add amazing feature'`
4. **Push to branch**: `git push origin feature/amazing-feature`
5. **Open a Pull Request** with:
   - Clear description of changes
   - Reference to related issues
   - Screenshots for UI changes
   - Test results

### Development Standards

- **Code Style**: Follow PEP 8 (Python) and Prettier (JavaScript)
- **Type Hints**: Use TypeScript on frontend, type hints on backend
- **Tests**: Write tests for new features (target 80%+ coverage)
- **Docstrings**: Document functions and classes
- **Commits**: Use conventional commits (`feat:`, `fix:`, `docs:`, etc.)

---

## 🆘 Troubleshooting

### Common Issues

#### Issue: `docker-compose: command not found`
**Solution**: Install Docker Desktop (includes Docker Compose)

#### Issue: `ModuleNotFoundError: No module named 'fastapi'`
**Solution**:
```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
```

#### Issue: `Cannot connect to localhost:5432 (PostgreSQL)`
**Solution**:
```bash
# Using Docker:
docker-compose up -d postgres

# Check if running:
docker-compose ps postgres
```

#### Issue: `npm ERR! code EACCES` (permission denied)
**Solution** (Linux/macOS):
```bash
sudo npm install -g npm
cd frontend
npm install
```

#### Issue: `CORS errors` when calling backend
**Solution**: Check `NEXT_PUBLIC_API_URL` matches backend URL in frontend `.env.local`

#### Issue: `Redis connection refused`
**Solution**:
```bash
# Start Redis via Docker:
docker-compose up -d redis

# Or install locally and start:
redis-server
```

#### Issue: `JWTClaimsError` or authentication issues
**Solution**:
1. JWT verification is now automatic via JWKS public keys
2. Ensure `SUPABASE_URL` is correct in `backend/.env`
3. Clear browser cookies
4. Re-login

#### Issue: Database migration fails
**Solution**:
```bash
cd backend
# Check migration status:
alembic current

# View migration history:
alembic history

# Downgrade if needed:
alembic downgrade -1
```

### Debug Logging

**Backend**:
```python
# In your Python code
import logging
logger = logging.getLogger(__name__)
logger.debug(f"Debug info: {variable}")
logger.error(f"Error occurred: {error}")
```

**Frontend**:
```typescript
// In your TypeScript/JavaScript
console.log("Debug info:", variable);
console.error("Error occurred:", error);
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

**You are free to**:
- Use this software for commercial and private purposes
- Modify and distribute the code
- Use it in proprietary applications

**You must**:
- Include the original license and copyright notice
- Document all significant changes

---

## 💬 Support

### Getting Help

1. **Check this README** — Most common questions are answered here
2. **Read documentation** — See `PRD.txt`, `system_architecture.md`, `TechStack.txt`
3. **Search existing issues** — https://github.com/your-username/equated/issues
4. **Create an issue** — [Report a bug or request feature](https://github.com/your-username/equated/issues/new)

### Contact & Community

- **Email**: support@equated.dev
- **Discord**: [Join our community](https://discord.gg/equated)
- **Twitter**: [@EquatedApp](https://twitter.com/EquatedApp)

---

## 📊 Project Status

- ✅ **MVP**: Core problem-solving and verification
- 🔄 **In Development**: Hint system, visualization engine, study tools
- 📅 **Planned**: Mobile app, API for partners, premium analytics

---

## 🙏 Acknowledgments

- Built with ❤️ for STEM students everywhere
- Special thanks to the open-source community (SymPy, FastAPI, Next.js, etc.)
- Powered by DeepSeek, Groq, and community AI models

---

**Last Updated**: March 2026  
**Current Version**: 1.0.0-beta
├── backend/          # FastAPI microservice
│   ├── ai/           # Model router, classifier, cost optimizer
│   ├── cache/        # Redis + vector cache layers
│   ├── config/       # Settings, feature flags
│   ├── db/           # Database connection & models
│   ├── gateway/      # Rate limiting, auth, request logging
│   ├── monitoring/   # Logging, metrics, tracing
│   ├── routers/      # API endpoints
│   ├── services/     # Business logic (math, parsing, streaming)
│   ├── workers/      # Celery background tasks
│   └── tests/        # Unit & integration tests
├── frontend/         # Next.js 14 app
│   └── src/
│       ├── app/      # App Router pages
│       ├── components/
│       ├── hooks/
│       ├── lib/
│       ├── store/
│       ├── types/
│       └── utils/
├── database/         # SQL schema, migrations, seed data
├── infra/            # Docker, CI/CD, nginx, env configs
├── ai/               # Shared AI config (model registry, costs)
└── scripts/          # Dev helper scripts
```

## Docs

- [PRD v2.0](./PRD.txt)
- [Tech Stack Guide](./TechStack.txt)
- [System Architecture](./system_architecture.md)
