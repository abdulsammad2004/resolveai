# ResolveAI API Service

FastAPI backend service for ResolveAI multi-tenant AI customer support SaaS.

## Development Setup (Windows PowerShell)

### 1. Start Infrastructure Services
Start PostgreSQL (with pgvector) and Redis using Docker Compose:
```powershell
docker compose -f ../../infra/docker-compose.yml up -d
```

### 2. Create and Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -e ".[dev]"
```

### 4. Configure Environment
```powershell
Copy-Item .env.example .env
```

### 5. Run Database Migrations
```powershell
# Create a new migration revision:
alembic revision --autogenerate -m "initial migration"

# Apply migrations to head:
alembic upgrade head
```

### 6. Run the Development Server
```powershell
uvicorn app.main:app --reload --port 8000
```

### 7. Run Linting and Tests
```powershell
# Check code style with Ruff:
ruff check .

# Run test suite:
pytest
```

