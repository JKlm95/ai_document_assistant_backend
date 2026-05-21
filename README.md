# AI Document Assistant Backend

FastAPI backend foundation for an AI Document Assistant MVP.

## Local Setup

1. Create environment file:

```bash
cp .env.example .env
```

2. Start services:

```bash
docker compose up --build
```

3. Run migrations:

```bash
docker compose exec api alembic upgrade head
```

4. Check health endpoint:

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:

```json
{"status":"ok"}
```

## Development Without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Useful Commands

```bash
ruff check .
pytest
alembic upgrade head
```
