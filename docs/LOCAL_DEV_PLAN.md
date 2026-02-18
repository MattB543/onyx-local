# Onyx Local Development Plan

> **Platform**: Windows (PowerShell)
> **Last Updated**: 2026-02-17
> **Repository Root**: `C:\Users\matth\projects\onyx-test\onyx-local`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites (All Options)](#prerequisites-all-options)
3. [Plan Options](#plan-options)
   - [Option A: Full Docker (Simplest)](#option-a-full-docker-simplest)
   - [Option B: Hybrid Local Dev (Recommended)](#option-b-hybrid-local-dev-recommended)
   - [Option C: Hybrid + Production DB Proxy](#option-c-hybrid--production-db-proxy)
4. [Production DB Connection Guide](#production-db-connection-guide)
5. [VSCode Debugger Workflow (Recommended by Onyx Team)](#vscode-debugger-workflow)
6. [Live Shared Logs (Multi-Agent Friendly)](#live-shared-logs-multi-agent-friendly)
7. [Gotchas and Tips](#gotchas-and-tips)
8. [Environment Variable Reference](#environment-variable-reference)
9. [Service Port Reference](#service-port-reference)

---

## Architecture Overview

Onyx consists of several interconnected services:

| Service | Technology | Default Port | Purpose |
|---------|-----------|-------------|---------|
| **Frontend (web)** | Next.js (Node 22) | 3000 | UI, proxies `/api/*` to backend |
| **API Server** | FastAPI (Python 3.11) | 8080 | Main REST API |
| **Model Server** | FastAPI (Python 3.11) | 9000 | Local NLP model inference |
| **Background Jobs** | Celery (Python 3.11) | N/A | Async task processing |
| **PostgreSQL** | Postgres 15.2 | 5432 | Relational database |
| **Vespa** | Vespa 8.609.39 | 8081, 19071 | Vector DB / search engine |
| **Redis** | Redis 7.4 | 6379 | Cache and Celery broker |
| **MinIO** | MinIO | 9004, 9005 | S3-compatible file storage |
| **Nginx** | Nginx 1.25 | 80/3000 | Reverse proxy (Docker only) |

**In development mode**, Nginx is NOT needed. The Next.js dev server has a built-in catch-all
API proxy at `web/src/app/api/[...path]/route.ts` that forwards `/api/*` requests to the
backend (recommended: `http://127.0.0.1:8080` on Windows). This is controlled by the `INTERNAL_URL`
environment variable.

---

## Prerequisites (All Options)

### 1. Docker Desktop for Windows
- Download and install from https://www.docker.com/products/docker-desktop/
- Ensure it is running before starting any Docker commands
- WSL2 backend is recommended

### 2. Python 3.11 (for Options B and C)
**CRITICAL**: Python 3.11 specifically. Python 3.12+ breaks TensorFlow and other dependencies.

Install via `uv` (recommended):
```powershell
# Install uv if not already installed
pip install uv

# Or via the standalone installer:
# powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3. Node.js v22.20.0 (for Options B and C)
Use nvm-windows (https://github.com/coreybutler/nvm-windows):
```powershell
nvm install 22
nvm use 22
node -v  # verify: should show v22.x.x
```

### 4. System Requirements
- **CPU**: 4 vCPU minimum
- **RAM**: 10 GB minimum (Vespa alone needs several GB)
- **Storage**: 32 GB minimum

---

## Plan Options

### Option A: Full Docker (Simplest)

**What you get**: Entire Onyx stack running in containers. Access at http://localhost:3000.
**What you lose**: No hot reload, no debugging, slower iteration cycle. Must rebuild containers for code changes.
**Best for**: Quick testing, verifying a build works, running integration tests.

#### Steps

```powershell
# 1. Navigate to docker compose directory
cd C:\Users\matth\projects\onyx-test\onyx-local\deployment\docker_compose

# 2. (Optional) Create a .env file from template for customization
copy env.template .env
# Edit .env if needed (defaults work out of the box)

# 3. Start the full stack
docker compose up -d

# 4. Wait for services to be healthy (may take 2-5 minutes on first run)
docker compose ps

# 5. Access Onyx at http://localhost:3000
# You will see the onboarding wizard on first launch
```

**To rebuild after code changes:**
```powershell
docker compose up -d --build
```

**To stop:**
```powershell
docker compose down
```

**To reset all data (nuclear option):**
```powershell
docker compose down -v
```

#### Tradeoffs
| Aspect | Status |
|--------|--------|
| Hot Reload (FE) | NO |
| Hot Reload (BE) | NO |
| Debugging | NO (no breakpoints) |
| Setup Time | ~5 minutes |
| Resource Usage | High (all containers) |
| Code Changes | Requires rebuild |

---

### Option B: Hybrid Local Dev (Recommended)

**What you get**: Frontend and backend running locally with hot reload. Infrastructure
(Postgres, Vespa, Redis) in Docker by default, with optional MinIO. Full debugging support.
**Best for**: Active development, daily workflow.

There are two sub-approaches:
- **B1: Manual Terminal** -- run each service in a separate terminal
- **B2: VSCode Debugger** -- use pre-configured launch configs (recommended by Onyx team)

---

#### Option B1: Manual Terminal Approach

##### Step 1: Start Infrastructure in Docker

```powershell
# From repo root
cd C:\Users\matth\projects\onyx-test\onyx-local
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1
```

This starts the default local infra:
- `relational_db` (Postgres) on port **5432**
- `index` (Vespa) on ports **8081** and **19071**
- `cache` (Redis) on port **6379**

Optional MinIO startup:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1 -WithMinio
```

> **Default recommendation**: use `FILE_STORE_BACKEND=postgres` for local dev to keep the
> stack smaller and avoid MinIO unless you are explicitly testing S3 behavior.

The helper script waits for startup. To re-check status later:
```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local\deployment\docker_compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
```

##### Step 2: Set Up Python Environment

```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local

# Create virtual environment with Python 3.11
uv venv .venv --python 3.11

# Activate it (PowerShell)
.venv\Scripts\Activate.ps1

# Install all Python dependencies
uv sync --all-extras

# Install Playwright (for web connector)
uv run playwright install
```

##### Step 3: Set Up Frontend

```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local\web

npm install
```

##### Step 4: Run Database Migrations (first time only, or after schema changes)

```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local\backend

# Make sure venv is activated
alembic upgrade head
```

##### Step 5: Start App Services (4 separate terminals)

Use the helper launcher:

```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local
powershell -ExecutionPolicy Bypass -File start_dev.ps1
```

Or launch services individually:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_model_server.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_api_server.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_bg_jobs.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_frontend.ps1
```

These scripts set the recommended local env defaults (including
`FILE_STORE_BACKEND=postgres` and `INTERNAL_URL=http://127.0.0.1:8080`) and write
live logs to `.dev\logs\`.

##### Step 6: Tail Shared Logs (optional but recommended)

```powershell
# Tail all app logs in one terminal
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1

# Tail only API logs
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1 -Service api
```

##### Step 7: Access Onyx

Open http://localhost:3000 in your browser. You will see the onboarding wizard.

Stop commands:
```powershell
# Stop local app processes
powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1

# Stop Docker infra
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1 -Down
```

> **Important Auth Change**: `AUTH_TYPE=disabled` is **no longer supported**. The codebase
> now automatically upgrades it to `basic`. Use `AUTH_TYPE=basic` with `DEV_MODE=true`.
> On first launch you will create an admin account with email/password.

---

#### Option B2: VSCode Debugger Approach (Recommended)

This is the approach the Onyx team officially recommends. It provides breakpoints,
variable inspection, and organized console output.

##### Step 1: Set Up Environment Files

```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local

# Copy env templates
copy .vscode\env_template.txt .vscode\.env
copy .vscode\env.web_template.txt .vscode\.env.web
```

Edit `.vscode\.env` and fill in at minimum:
```ini
AUTH_TYPE=basic
DEV_MODE=true
LOG_LEVEL=debug
DEV_LOGGING_ENABLED=true
PYTHONPATH=../backend
PYTHONUNBUFFERED=1
FILE_STORE_BACKEND=postgres

# Set this to avoid reconfiguring after DB wipes
GEN_AI_API_KEY=sk-your-openai-key-here
OPENAI_API_KEY=sk-your-openai-key-here
GEN_AI_MODEL_VERSION=gpt-4o

# Not needed for basic dev
REQUIRE_EMAIL_VERIFICATION=False
```

The `.vscode\.env.web` file for the frontend typically needs:
```ini
AUTH_TYPE=basic
DEV_MODE=true
INTERNAL_URL=http://127.0.0.1:8080
ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false
ENABLE_CRAFT=true
```

##### Step 2: Install Dependencies (same as B1, Steps 2 and 3)

Run the Python and Node setup steps from Option B1 above.

##### Step 3: Start Infrastructure

Recommended:
```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local
powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1
```

You can still use VSCode's **"Clear and Restart External Volumes and Containers"**, but:
- It is **destructive** (wipes Postgres + Vespa data)
- It invokes `backend/scripts/restart_containers.sh` via bash, requiring Git Bash or WSL

##### Step 4: Launch Services

In VSCode Debug view:
1. Start **"Web / Model / API"** first:
   - Web Server (frontend)
   - Model Server
   - API Server

2. Then launch **"Celery (lightweight mode)"** for background jobs.

Use **"Run All Onyx Services"** only when you specifically need MCP + Slack + full Celery topology.

##### Step 5: Debug

- Set breakpoints by clicking to the left of line numbers
- Use the debug toolbar to step through code
- Each service has its own labeled console tab

##### Available VSCode Launch Compounds:

| Compound | Services Started | Use Case |
|----------|-----------------|----------|
| Run All Onyx Services | Web + Model + API + MCP + Slack + 7 Celery workers | Full stack |
| Web / Model / API | Web + Model + API only | FE/BE development |
| Celery (lightweight mode) | primary + background + beat | Minimal background jobs |
| Celery (standard mode) | primary + light + heavy + kg + monitoring + user_file + docfetching + docprocessing + beat | Full background processing |

##### Available VSCode Database Tasks:

| Task | Purpose |
|------|---------|
| Restore seeded database dump | Load a pre-built DB with sample data |
| Clean restore seeded database dump | Same, but drops existing data first |
| Create database snapshot | Save current DB state to `backup.dump` |
| Clean restore database snapshot | Restore from `backup.dump` |
| Upgrade database to head revision | Run alembic migrations |

---

#### Option B Tradeoffs

| Aspect | Status |
|--------|--------|
| Hot Reload (FE) | YES |
| Hot Reload (BE API) | YES |
| Hot Reload (Model Server) | YES |
| Hot Reload (Celery Workers) | NO -- must restart manually |
| Debugging | YES (breakpoints, variable inspection) |
| Setup Time | ~15-20 minutes first time |
| Resource Usage | Medium (Docker for infra, local for app) |
| Code Changes | Instant for FE and BE API |

---

### Option C: Hybrid + Production DB Proxy

**What you get**: Local frontend and backend with hot reload, but connected to a remote
(production or staging) database for testing against real data.
**Best for**: Debugging production issues, testing migrations, verifying behavior with real data.

**WARNING**: This carries real risk. See the [Security Considerations](#security-considerations)
section below before proceeding.

#### Steps

Follow all steps from Option B, but override the database connection environment variables
to point at your remote database.

##### Backend Environment Variables

In your `.vscode\.env` or terminal environment, set:

```ini
# Remote PostgreSQL
POSTGRES_HOST=your-prod-db-host.example.com
POSTGRES_PORT=5432
POSTGRES_USER=your_readonly_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=postgres
```

If connecting through an SSH tunnel (recommended):

**Terminal 0 -- SSH Tunnel:**
```powershell
ssh -L 5433:prod-db-host:5432 bastion-user@bastion-host.example.com -N
```

Then use:
```ini
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5433
```

##### What Else Needs to Be Remote?

| Service | Can be remote? | Should be remote? | Notes |
|---------|---------------|-------------------|-------|
| **PostgreSQL** | Yes | Depends on use case | Main candidate for remote connection |
| **Vespa** | Yes (set `VESPA_HOST`) | Usually NO | Contains search indexes, must match DB state |
| **Redis** | Yes (set `REDIS_HOST`) | Usually NO | Ephemeral cache, local is fine |
| **MinIO** | Yes (set `S3_ENDPOINT_URL`) | Usually NO | File storage, can use local or `FILE_STORE_BACKEND=postgres` |

**Can you mix remote Postgres with local Vespa/Redis?**

Yes, but with caveats:
- The local Vespa will be empty while Postgres has document references. Searches will
  return no results until you re-index.
- Redis is ephemeral and local Redis works fine regardless.
- This is most useful for testing API behavior, admin features, or auth flows that
  depend on DB state but not search.

If you need search to work, you must either:
1. Also point Vespa to the remote instance (`VESPA_HOST=remote-vespa-host`)
2. Run a local re-index after connecting to the remote Postgres

#### Frontend-Only Remote Connection (Simplest Remote Option)

If you only need to develop the **frontend** against a remote backend, use the documented
approach from `web/README.md`. Create `web/.env.local`:

```ini
# Point local Next.js dev server at a remote backend
INTERNAL_URL=https://your-staging-server.example.com/api

# Auth cookie from the remote server (get from browser DevTools)
# DevTools -> Application -> Cookies -> find "fastapiusersauth" cookie
DEBUG_AUTH_COOKIE=your_cookie_value_here
```

Then just run:
```powershell
cd C:\Users\matth\projects\onyx-test\onyx-local\web
npm run dev
```

This gives you hot-reloading frontend development against a fully functional remote backend.
No need to run any local backend services, Docker containers, or infrastructure.

**Notes:**
- The `DEBUG_AUTH_COOKIE` is only used in development mode
- The cookie may expire; refresh it from the remote server periodically
- If you have existing localhost cookies, clear them first

---

## Production DB Connection Guide

### Connection Mechanics

The Onyx backend constructs its PostgreSQL connection string from environment variables
(defined in `backend/onyx/configs/app_configs.py`):

```
postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}
```

Defaults:
- `POSTGRES_USER` = `postgres`
- `POSTGRES_PASSWORD` = `password` (URL-encoded automatically for special characters)
- `POSTGRES_HOST` = `127.0.0.1`
- `POSTGRES_PORT` = `5432`
- `POSTGRES_DB` = `postgres`

The password is URL-encoded via `urllib.parse.quote_plus()` so special characters are safe.

### Connection Pooling

Configurable pool settings (useful when connecting to a remote DB with connection limits):

```ini
POSTGRES_API_SERVER_POOL_SIZE=40          # default
POSTGRES_API_SERVER_POOL_OVERFLOW=10      # default
POSTGRES_USE_NULL_POOL=false              # set true for serverless/Lambda patterns
POSTGRES_POOL_PRE_PING=false             # set true for unreliable connections
POSTGRES_POOL_RECYCLE=1200               # seconds, default 20 minutes
```

### AWS RDS IAM Auth

If your production DB is on AWS RDS with IAM authentication:

```ini
USE_IAM_AUTH=true
AWS_REGION_NAME=us-east-2
```

### Read-Only User Support

Onyx supports a separate read-only database user for analytics/reporting queries:

```ini
DB_READONLY_USER=db_readonly_user
DB_READONLY_PASSWORD=your_readonly_password
```

### Security Considerations

1. **Always use a read-only user** when connecting to production. The main application
   user has full DDL/DML permissions.

2. **Use an SSH tunnel** rather than exposing the database directly:
   ```powershell
   ssh -L 5433:prod-db-host:5432 bastion@bastion.example.com -N
   ```

3. **Never run `alembic upgrade head`** against a production database from your local
   machine. Migrations should go through your CI/CD pipeline.

4. **Be careful with Celery workers**. If connected to production, background jobs could
   modify production data. Consider running ONLY the API server and frontend when
   connected to a remote DB.

5. **Multi-tenant support**: Onyx uses PostgreSQL schemas with a `tenant_` prefix for
   multi-tenant deployments. If you are connecting to a multi-tenant production DB,
   ensure you understand which tenant schema you are operating on.

---

## VSCode Debugger Workflow

The Onyx team strongly recommends using the VSCode debugger for development. The
repository ships with pre-configured launch configurations in `.vscode/launch.json`.

### Quick Start

1. Copy env templates:
   ```powershell
   copy .vscode\env_template.txt .vscode\.env
   copy .vscode\env.web_template.txt .vscode\.env.web
   ```
2. Edit `.vscode\.env` -- fill in `GEN_AI_API_KEY` at minimum
3. Start Docker infrastructure:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_infra.ps1
   ```
4. Open Debug view (Ctrl+Shift+D)
5. Run "Web / Model / API"
6. Run "Celery (lightweight mode)" if you need background jobs

### Features
- **Hot reload** for Web Server and API Server
- **Python debugging** with debugpy (breakpoints, step-through, variable inspection)
- **Organized console output** with labeled terminal tabs
- **Database management** tasks built into VSCode

### Windows-Specific Note for "Clear and Restart External Volumes and Containers"

The `restart_containers.sh` script is a **bash script**. On Windows, the VSCode launch
config invokes it via `bash`. This requires one of:
- **Git Bash** (installed with Git for Windows)
- **WSL** (Windows Subsystem for Linux)

If neither is available, start infrastructure manually with the Docker Compose command.

---

## Live Shared Logs (Multi-Agent Friendly)

For local multi-terminal/multi-agent work, use shared log files under:

`C:\Users\matth\projects\onyx-test\onyx-local\.dev\logs`

Files:
- `web.log`
- `api.log`
- `model.log`
- `bg.log`

These are written automatically by:
- `scripts/run_frontend.ps1`
- `scripts/run_api_server.ps1`
- `scripts/run_model_server.ps1`
- `scripts/run_bg_jobs.ps1`
- `start_dev.ps1` (which launches the scripts above)

Tail all logs live:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1
```

Tail one service:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\tail_logs.ps1 -Service api
```

This makes it easy for multiple coding agents in different terminals to inspect the same
live output stream without owning the original service terminal.

---

## Gotchas and Tips

### Windows-Specific Issues

1. **`restart_containers.sh` requires bash**: This script will not work in PowerShell
   or CMD directly. Use Git Bash, WSL, or start infrastructure with Docker Compose
   commands instead.

2. **PowerShell environment variables**: In PowerShell, set env vars with `$env:VAR = "value"`,
   not the Unix `VAR=value command` syntax.
   ```powershell
   # Correct (PowerShell)
   $env:AUTH_TYPE = "basic"
   uvicorn onyx.main:app --reload --port 8080

   # Also correct (single command)
   powershell -Command "$env:AUTH_TYPE='basic'; uvicorn onyx.main:app --reload --port 8080"
   ```

3. **WEB_DOMAIN localhost issue**: If you cannot access `http://localhost:3000`, try
   setting `WEB_DOMAIN=http://127.0.0.1:3000` in your environment. The code in
   `app_configs.py` explicitly notes this Windows workaround.

4. **Line endings**: The Docker Compose nginx config uses `dos2unix` to handle Windows
   line endings. If you see issues with other shell scripts, convert them:
   ```powershell
   # In Git Bash or WSL
   dos2unix script.sh
   ```

5. **nvm-windows vs nvm**: Use nvm-windows (https://github.com/coreybutler/nvm-windows),
   not the Unix nvm. They are different projects.

### Common Failures and Fixes

1. **Alembic migration fails on startup**:
   - Postgres may not be fully ready. Wait a few seconds after starting the container.
   - Check that Postgres is accepting connections: `docker logs <postgres_container_id>`
   - Run `alembic upgrade head` from the `backend/` directory with the venv activated.

2. **`AUTH_TYPE=disabled` no longer works**:
   - The codebase now logs a warning and forces `AUTH_TYPE=basic`.
   - Use `AUTH_TYPE=basic` with `DEV_MODE=true` instead.
   - You will need to create an account on first launch.

3. **Celery workers do NOT hot-reload**:
   - When you change Celery task code, you must restart the background jobs manually.
   - The API server and model server DO hot-reload with uvicorn's `--reload` flag.

4. **Vespa takes a long time to start**:
   - Vespa can take 30-60 seconds to become healthy on first start.
   - The healthcheck uses `curl http://localhost:19071/state/v1/health`.
   - If Vespa fails to start, check Docker resource limits (needs several GB of RAM).

5. **MinIO not starting (when explicitly enabled)**:
   - MinIO is optional for local dev; default flow uses `FILE_STORE_BACKEND=postgres`.
   - If you need MinIO, run `scripts\run_infra.ps1 -WithMinio`.
   - If using MinIO, ensure ports 9004 and 9005 are not in use.

6. **Python version mismatch**:
   - `uv venv .venv --python 3.11` will fail if Python 3.11 is not installed.
   - Install Python 3.11 explicitly. Do not rely on system Python.

7. **Port conflicts**:
   - If port 5432 is already in use (local Postgres install), either stop the local
     Postgres or change the Docker port mapping.
   - Same for Redis (6379) or any other port.

### Performance Tips

1. **Use "Web / Model / API" compound** instead of "Run All Onyx Services" if you do not
   need background processing. This saves significant RAM.

2. **Use Celery (lightweight mode)** -- it runs a single consolidated background worker
   instead of 7+ separate ones. This is the default in the `dev_run_background_jobs.py`
   script.

3. **Set `FILE_STORE_BACKEND=postgres`** to skip running MinIO entirely, reducing container
   count by one.

4. **Use shared logs** in `.dev\logs\` with `scripts\tail_logs.ps1` so multiple terminals
   (or coding agents) can inspect output simultaneously.

5. **Pre-set `GEN_AI_API_KEY`** in `.vscode/.env` so you do not have to reconfigure the
   LLM provider every time the database is wiped.

6. **Use `gpt-4o-mini`** instead of `gpt-4o` during development if answer quality is not
   critical -- it is significantly cheaper and faster.

7. **Database seeding**: Use the VSCode task "Restore seeded database dump" to quickly get
   a pre-populated database instead of setting up connectors manually each time:
   ```powershell
   uv run --with onyx-devtools ods db restore --fetch-seeded --yes
   ```

---

## Environment Variable Reference

### Critical Development Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `AUTH_TYPE` | `basic` | Authentication method (disabled is no longer supported) |
| `DEV_MODE` | `true` | Enables dev-specific behaviors (unlimited tenant limits, OAuth relaxation) |
| `GEN_AI_API_KEY` | your API key | Persists LLM config across DB wipes |
| `OPENAI_API_KEY` | your API key | Same as above (some code paths check this) |
| `GEN_AI_MODEL_VERSION` | `gpt-4o` or `gpt-4o-mini` | Default LLM model |
| `LOG_LEVEL` | `debug` | Verbose logging for development |
| `DEV_LOGGING_ENABLED` | `true` | Enables backend file logs under `backend/log` |
| `PYTHONPATH` | `../backend` or `.` | Required for module resolution |
| `PYTHONUNBUFFERED` | `1` | Ensures Python output is not buffered |

### File Store Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `FILE_STORE_BACKEND` | `postgres` (recommended) / `s3` | Use `postgres` to skip MinIO |
| `S3_ENDPOINT_URL` | `http://localhost:9004` | MinIO endpoint |
| `S3_FILE_STORE_BUCKET_NAME` | `onyx-file-store-bucket` | MinIO bucket name |
| `S3_AWS_ACCESS_KEY_ID` | `minioadmin` | MinIO access key |
| `S3_AWS_SECRET_ACCESS_KEY` | `minioadmin` | MinIO secret key |

### Database Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `POSTGRES_HOST` | `127.0.0.1` (local) / `relational_db` (Docker) | DB host |
| `POSTGRES_PORT` | `5432` | DB port |
| `POSTGRES_USER` | `postgres` | DB username |
| `POSTGRES_PASSWORD` | `password` | DB password |
| `POSTGRES_DB` | `postgres` | DB name |

### Service Host Variables (for remote connections)

| Variable | Default (local dev) | Purpose |
|----------|-------------------|---------|
| `POSTGRES_HOST` | `127.0.0.1` | PostgreSQL host |
| `VESPA_HOST` | `localhost` | Vespa host |
| `VESPA_PORT` | `8081` | Vespa application port |
| `VESPA_TENANT_PORT` | `19071` | Vespa config port |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `MODEL_SERVER_HOST` | `localhost` (native local dev) / `inference_model_server` (Docker) | Model server host |

### Frontend Variables (set in `web/.env.local` or `.vscode/.env.web`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `INTERNAL_URL` | `http://127.0.0.1:8080` (Windows recommended) | Backend URL the frontend proxies to |
| `DEBUG_AUTH_COOKIE` | (none) | Auth cookie for remote backend dev |
| `AUTH_TYPE` | `basic` | Must match backend |
| `DEV_MODE` | `true` | Dev mode flag |

---

## Service Port Reference

Ports exposed by `docker-compose.dev.yml`:

| Service | Container Port | Host Port | Protocol |
|---------|---------------|-----------|----------|
| API Server | 8080 | 8080 | HTTP |
| PostgreSQL | 5432 | 5432 | TCP |
| Vespa (config) | 19071 | 19071 | HTTP |
| Vespa (app) | 8081 | 8081 | HTTP |
| Model Server | 9000 | 9000 | HTTP |
| Redis | 6379 | 6379 | TCP |
| MinIO (API) | 9000 | 9004 | HTTP |
| MinIO (Console) | 9001 | 9005 | HTTP |
| Code Interpreter | 8000 | 8000 | HTTP |
| Nginx | 80 | 80, 3000 | HTTP |

> **Note**: MinIO uses non-standard host ports (9004/9005) to avoid conflicts with the
> model server (port 9000).

---

## Quick Reference: Which Option to Choose

| Scenario | Recommended Option |
|----------|-------------------|
| "Just want to see Onyx running" | **Option A** (Full Docker) |
| "Daily local dev with shared logs" | **Option B1** (`start_dev.ps1` + `tail_logs.ps1`) |
| "Developing frontend features" | **Option B2** (VSCode) or **Frontend-only remote** |
| "Developing backend API" | **Option B2** (VSCode) |
| "Developing Celery tasks" | **Option B** (either sub-option, accept manual restarts) |
| "Debugging a production issue" | **Option C** (with SSH tunnel + read-only user) |
| "Testing UI against real data" | **Frontend-only remote** (simplest) |
| "Full stack with breakpoints" | **Option B2** (`Web / Model / API` + `Celery (lightweight mode)`) |
