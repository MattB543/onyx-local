# Onyx Local Dev Runbook (Windows / PowerShell)

This is the practical ops runbook for local development in this repo.
It is based on the actual scripts/config in:
- `scripts/*.ps1`
- `start_dev.ps1`
- `backend/scripts/dev_run_background_jobs.py`
- `deployment/docker_compose/docker-compose*.yml`
- `.vscode/launch.json`

## 1) One-Time Setup

Unless noted otherwise, Python commands below assume `.venv` is active in that shell.

From repo root:

```powershell
uv venv .venv --python 3.11
.venv\Scripts\Activate.ps1
uv sync --all-extras
uv run playwright install
```

Frontend deps:

```powershell
cd web
npm install
cd ..
```

Run DB migrations at least once:

```powershell
cd backend
alembic upgrade head
cd ..
```

## 2) Recommended Daily Start (Hybrid Local Dev)

1. Start infra (Docker: Postgres + Vespa + Redis):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1
```

Optional MinIO (only needed for S3 file-store testing):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1 -WithMinio
```

2. Start app services (opens separate terminals):

```powershell
powershell -ExecutionPolicy Bypass -File start_dev.ps1
```

This launches:
- Frontend (`web`, port 3000)
- API server (`uvicorn`, port 8080)
- Model server (`uvicorn`, port 9000)
- Background jobs (`dev_run_background_jobs.py`)

Background jobs include primary/light/docfetching/docprocessing/beat and a lightweight `background` worker.
Indexer behavior in local dev is split across:
- `docfetching` + `docprocessing` workers (in background jobs)
- Vespa container (`index`)

3. Open:
- `http://localhost:3000`

## 3) Health/Status Checks

### Infra

```powershell
cd deployment\docker_compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
cd ..\..
```

### HTTP checks

```powershell
Invoke-WebRequest http://localhost:3000 | Select-Object StatusCode
Invoke-WebRequest http://localhost:3000/api/health | Select-Object StatusCode
Invoke-WebRequest http://127.0.0.1:9000/api/health | Select-Object StatusCode
Invoke-WebRequest http://127.0.0.1:19071/state/v1/health | Select-Object StatusCode
```

Note: prefer backend calls through frontend proxy (`http://localhost:3000/api/...`) during local testing.

### Process checks (local services)

```powershell
Get-Process -Name node,uvicorn,celery -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 3000,8080,9000 -ErrorAction SilentlyContinue
```

Background/indexer quick signal:

```powershell
Get-Content .dev\logs\bg.log -Tail 120
```

## 4) Logs

### Unified local logs

```powershell
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1
```

Service-specific:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1 -Service web
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1 -Service api
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1 -Service model
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1 -Service bg
```

Files:
- `.dev\logs\web.log`
- `.dev\logs\api.log`
- `.dev\logs\model.log`
- `.dev\logs\bg.log`

Additional backend file logs (when `DEV_LOGGING_ENABLED=true`):
- `backend\log\onyx_debug.log`
- `backend\log\onyx_info.log`
- `backend\log\onyx_notice.log`

Docker infra logs:

```powershell
cd deployment\docker_compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f index relational_db cache
cd ..\..
```

## 5) Restart

### Restart all local app services (FE/API/model/background)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1
powershell -ExecutionPolicy Bypass -File start_dev.ps1
```

### Restart infra only

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1 -Down
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1
```

### Restart one service

Frontend:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_frontend.ps1
```

API:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_api_server.ps1
```

Model:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_model_server.ps1
```

Background/indexer workers:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_bg_jobs.ps1
```

Important: celery workers do not hot-reload task code. Restart background jobs after celery/task changes.

## 6) Stop / End Session

Stop local app processes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1
```

Stop infra containers:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1 -Down
```

## 7) Database and Index Operations

Run migrations:

```powershell
cd backend
alembic upgrade head
cd ..
```

Quick SQL against local Postgres:

```powershell
docker exec -it onyx-relational_db-1 psql -U postgres -c "SELECT now();"
```

Destructive reset helpers:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\reset_postgres.py
..\.venv\Scripts\python.exe scripts\reset_indexes.py
cd ..
```

After destructive resets, restart API/background services.

## 8) Full Docker Mode (Alternative)

Use this when you want everything containerized (no local hot reload).

Start all services:

```powershell
cd deployment\docker_compose
docker compose up -d
```

Check status:

```powershell
docker compose ps
```

Tail logs:

```powershell
docker compose logs -f web_server api_server background relational_db index cache
```

Restart selected services:

```powershell
docker compose restart web_server api_server background
```

Stop:

```powershell
docker compose down
```

Destroy all compose data (destructive):

```powershell
docker compose down -v
```

## 9) Known Gotchas

- `AUTH_TYPE=disabled` is no longer supported; use `AUTH_TYPE=basic`.
- If you run local FE/API, keep frontend `INTERNAL_URL` pointed to backend (`http://127.0.0.1:8080` in provided scripts).
- If ports are busy (3000/8080/9000/5432/6379/8081/19071), free them before startup.
