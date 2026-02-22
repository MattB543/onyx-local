# Deployment to Production (EC2)

Complete guide to deploying code changes to the production EC2 instance running Onyx via Docker Compose.

---

## Prerequisites

| Item | Value |
|------|-------|
| EC2 IP / Host | `<set via PROD_HOST env var>` |
| SSH Key | `<set via SSH_KEY_PATH env var>` |
| SSH User | `<set via SSH_USER env var>` |
| Repo on EC2 | `/home/ec2-user/onyx-local` |
| Compose file | `deployment/docker_compose/docker-compose.prod.yml` |

Services in the stack: `api_server`, `background`, `web_server`, `inference_model_server`, `indexing_model_server`, `nginx`, `relational_db`, `cache`, `index`, `minio`, `certbot`, `code-interpreter`

Before running any SSH commands, set these local shell variables:

```bash
export PROD_HOST="<prod host or ip>"
export SSH_USER="<ssh username>"
export SSH_KEY_PATH="<absolute path to ssh key>"
```

---

## Step 1: Commit and Push (Local Machine)

From your local `onyx-local` repository root:

```bash
git add -A
git commit -m "your commit message"
git push origin main
```

---

## Step 2: SSH In, Pull, and Rebuild (EC2)

```bash
ssh -i "${SSH_KEY_PATH}" "${SSH_USER}@${PROD_HOST}"
```

Once on EC2:

```bash
cd /home/ec2-user/onyx-local
git pull origin main
```

Rebuild and restart all changed services:

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml up -d --build --force-recreate api_server background web_server
```

- `--build` rebuilds images from source (required since we are not using pre-built images).
- `--force-recreate` ensures containers are fully recreated even if the image hash appears unchanged.
- List only the services you changed, or omit service names to rebuild everything.

---

## Step 3: Restart nginx (CRITICAL)

**This step is mandatory after rebuilding ANY service.** Nginx caches the internal Docker container IP addresses. When a container is recreated, it gets a new IP, but nginx still points to the old one. This causes `502 Bad Gateway` or `Connection refused` errors.

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml restart nginx
```

> **Rule of thumb:** If you rebuilt anything, restart nginx. Always. Every time. No exceptions.

---

## Step 4: Verify

Check that all containers are running:

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml ps
```

Check logs for a specific service:

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml logs -f api_server --tail=100
docker compose -f deployment/docker_compose/docker-compose.prod.yml logs -f web_server --tail=100
docker compose -f deployment/docker_compose/docker-compose.prod.yml logs -f nginx --tail=100
```

Hit the site in a browser and confirm it loads without errors.

---

## Quick One-Liner (Full Deploy)

Run this single SSH command from your local machine to pull, rebuild all application services, and restart nginx in one shot:

```bash
ssh -i "${SSH_KEY_PATH}" "${SSH_USER}@${PROD_HOST}" "cd /home/ec2-user/onyx-local && git pull origin main && docker compose -f deployment/docker_compose/docker-compose.prod.yml up -d --build --force-recreate api_server background web_server && docker compose -f deployment/docker_compose/docker-compose.prod.yml restart nginx"
```

---

## Partial Rebuilds

### Backend only (API + background workers)

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml up -d --build --force-recreate api_server background
docker compose -f deployment/docker_compose/docker-compose.prod.yml restart nginx
```

### Frontend only (Next.js web server)

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml up -d --build --force-recreate web_server
docker compose -f deployment/docker_compose/docker-compose.prod.yml restart nginx
```

### Backend + Frontend

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml up -d --build --force-recreate api_server background web_server
docker compose -f deployment/docker_compose/docker-compose.prod.yml restart nginx
```

### Everything (nuclear option)

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml up -d --build --force-recreate
```

This rebuilds and recreates every service in the stack. Nginx is included so no separate restart is needed.

---

## Troubleshooting

### "Backend unavailable" or 502 errors after deploy

**Cause:** Nginx is still pointing to a stale container IP.

**Fix:**

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml restart nginx
```

### Container IP mismatch after rebuild

Same root cause as above. Whenever Docker recreates a container, it may assign a new internal IP. Nginx resolves service names to IPs at startup and caches them.

**Fix:** Restart nginx (see above).

### Redirect loops

**Cause:** Stale cookies or cached redirects, sometimes combined with nginx holding stale IPs.

**Fix:**
1. Restart nginx.
2. Clear browser cookies for the site (or use an incognito window).
3. If the issue persists, check nginx logs for clues:

```bash
docker compose -f deployment/docker_compose/docker-compose.prod.yml logs nginx --tail=200
```

### Checking logs for each service

```bash
# Live tail (Ctrl+C to stop)
docker compose -f deployment/docker_compose/docker-compose.prod.yml logs -f <service_name> --tail=100

# Common services to check:
#   api_server    - backend API
#   background    - background workers / tasks
#   web_server    - Next.js frontend
#   nginx         - reverse proxy
#   relational_db - PostgreSQL
```

### Running SQL against the database

Exec into the PostgreSQL container and open psql:

```bash
docker exec -it onyx-local-relational_db-1 psql -U postgres -d postgres
```

If the container name differs, find it first:

```bash
docker ps --filter "name=relational_db" --format "{{.Names}}"
```

Then use that name with `docker exec -it <name> psql -U postgres -d postgres`.

Useful queries:

```sql
-- List all tables
\dt

-- Check alembic migration version
SELECT * FROM alembic_version;

-- Exit psql
\q
```

### Docker buildx version issue

**Symptom:** Build fails with errors related to `docker buildx` or the builder not being found.

**Fix:** Ensure the buildx plugin is installed and the default builder is set:

```bash
# Check current buildx version
docker buildx version

# If outdated (needs 0.17.0+ for Docker Compose v5), update it:
# For ARM64 (m7g instances):
sudo curl -L https://github.com/docker/buildx/releases/download/v0.21.1/buildx-v0.21.1.linux-arm64 -o /usr/libexec/docker/cli-plugins/docker-buildx
sudo chmod +x /usr/libexec/docker/cli-plugins/docker-buildx

# For x86_64 instances:
# sudo curl -L https://github.com/docker/buildx/releases/download/v0.21.1/buildx-v0.21.1.linux-amd64 -o /usr/libexec/docker/cli-plugins/docker-buildx
# sudo chmod +x /usr/libexec/docker/cli-plugins/docker-buildx

# Verify
docker buildx version
```

### Container won't start / port conflicts

```bash
# See what is using a port
docker ps --format "table {{.Names}}\t{{.Ports}}"

# Force remove a stuck container
docker compose -f deployment/docker_compose/docker-compose.prod.yml rm -f <service_name>

# Then bring it back up
docker compose -f deployment/docker_compose/docker-compose.prod.yml up -d --build <service_name>
docker compose -f deployment/docker_compose/docker-compose.prod.yml restart nginx
```

---

## Summary Checklist

```
[ ] Code committed and pushed to origin/main
[ ] SSH into EC2
[ ] git pull origin main
[ ] docker compose up -d --build --force-recreate <services>
[ ] docker compose restart nginx    <-- DO NOT SKIP
[ ] Verify site loads in browser
[ ] Check logs if anything looks off
```
