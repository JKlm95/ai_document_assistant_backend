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

## Auth Smoke Test

Register:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"strong-password","full_name":"Test User"}'
```

Login:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"strong-password"}'
```

Get current user:

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

## Projects Smoke Test

Create project:

```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Research","description":"Private research workspace"}'
```

List projects:

```bash
curl "http://localhost:8000/api/v1/projects?limit=20&offset=0" \
  -H "Authorization: Bearer <access_token>"
```

Get, update, and archive a project:

```bash
curl http://localhost:8000/api/v1/projects/<project_id> \
  -H "Authorization: Bearer <access_token>"

curl -X PATCH http://localhost:8000/api/v1/projects/<project_id> \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Research","description":"Updated description"}'

curl -X DELETE http://localhost:8000/api/v1/projects/<project_id> \
  -H "Authorization: Bearer <access_token>"
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
