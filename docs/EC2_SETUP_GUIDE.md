# Onyx EC2 Setup Guide

Deploy Onyx on AWS EC2 in `us-east-2` behind Cloudflare Access + Cloudflare Tunnel, with:

- `.env` secrets loaded from AWS SSM Parameter Store at boot
- database-stored credentials encrypted with AWS KMS envelope encryption
- no email verification, no OAuth, and no password-reset flow
- a localhost-only origin on the EC2 instance instead of public `80/443`

This guide matches the repo state in this workspace. The Onyx-side deployment assets now live in-repo:

- `deployment/docker_compose/bootstrap-env.sh`
- `deployment/docker_compose/env.ec2.cloudflare.template`
- `deployment/docker_compose/docker-compose.prod-tunnel.yml`
- `deployment/docker_compose/onyx.service.tunnel`
- `deployment/data/nginx/app.conf.template.tunnel`

This repo still does **not** provision:

- the EC2 instance
- the IAM role
- the KMS key
- the SSM parameters
- the Cloudflare Tunnel daemon or Access policy

Those parts remain external AWS / Cloudflare setup.

---

## 1. Assumptions

- Region: `us-east-2` for **everything**
- AMI: Amazon Linux 2023 ARM64
- Public access: Cloudflare Access in front of a Cloudflare Tunnel
- Origin service: Onyx nginx bound to `127.0.0.1:8080`
- Onyx auth mode: `AUTH_TYPE=basic`
- Edition mode: MIT-only behavior with `LICENSE_ENFORCEMENT_ENABLED=false`

Cloudflare Access gates network access. It does **not** replace Onyx's own user accounts or sessions. The first user who signs up in Onyx still becomes the Onyx admin.

Because this guide does not use OAuth, email verification, or password resets:

- do **not** set SMTP secrets
- do **not** set OAuth secrets
- `USER_AUTH_SECRET` is not required for this path

If you later enable JWT auth backend, OAuth login, password resets, or email verification, add `USER_AUTH_SECRET` and the relevant OAuth / SMTP secrets then.

---

## 2. Secret Model

Onyx has two separate secret problems:

| Secret Type | Examples | Storage | Protection |
|-------------|----------|---------|------------|
| `.env` secrets | `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `GEN_AI_API_KEY` | `.env` on disk | SSM Parameter Store `SecureString`, fetched at boot |
| DB-stored secrets | connector tokens, admin-entered API keys, LLM provider secrets | PostgreSQL rows | AWS KMS envelope encryption in `backend/onyx/utils/encryption.py` |

Both use the same EC2 IAM role and the same KMS CMK.

---

## 3. EC2 Sizing And Network

### Instance sizing

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| Instance | `m7g.xlarge` | `m7g.2xlarge` |
| Memory | 16 GB | 32 GB |
| Disk | 32 GB + indexed data | 500 GB gp3 |

Vespa stops writes around 75% disk usage. Size storage accordingly.

### Security group

Because Cloudflare Tunnel connects outbound from the instance to Cloudflare, you do **not** need inbound `80` or `443`.

Recommended inbound rules:

| Port | Source | Purpose |
|------|--------|---------|
| `22` | Your IP only | SSH |

No public ingress is required for Onyx itself in this setup.

---

## 4. AWS Setup In `us-east-2`

Create all AWS resources in `us-east-2` before finishing the EC2 host setup.

### 4a. Create the KMS key

1. AWS Console → `KMS` → `us-east-2`
2. Create a symmetric customer-managed key for encrypt/decrypt
3. Alias: `alias/onyx-secrets-key`
4. Add your admin IAM principal as key administrator
5. Allow the EC2 instance role to use the key
6. Copy the KMS key ID UUID

### 4b. Create the EC2 IAM role

Attach an instance role that can:

- read SSM secrets under `/onyx/prod/*`
- decrypt the wrapped DEK with KMS
- generate new DEKs with KMS
- write rotated DEKs back to SSM

Replace `ACCOUNT_ID` and `KMS_KEY_ID`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KmsEnvelopeEncryption",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:us-east-2:ACCOUNT_ID:key/KMS_KEY_ID"
    },
    {
      "Sid": "ReadSsmSecrets",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParametersByPath"],
      "Resource": "arn:aws:ssm:us-east-2:ACCOUNT_ID:parameter/onyx/prod/*"
    },
    {
      "Sid": "WriteEncryptedDek",
      "Effect": "Allow",
      "Action": "ssm:PutParameter",
      "Resource": "arn:aws:ssm:us-east-2:ACCOUNT_ID:parameter/onyx/prod/encrypted_dek/*"
    }
  ]
}
```

Attach that role to the EC2 instance.

### 4c. Set IMDS hop limit to 2

SSM and KMS are called from inside Docker containers. Without hop limit `2`, the containers cannot reach instance metadata credentials reliably.

```bash
aws ec2 modify-instance-metadata-options \
  --instance-id <INSTANCE_ID> \
  --http-tokens required \
  --http-put-response-hop-limit 2 \
  --region us-east-2
```

### 4d. Store required `.env` secrets in SSM

Use `SecureString` and explicitly set `--key-id alias/onyx-secrets-key` so the same CMK protects the SSM values at rest.

```bash
REGION=us-east-2
SSM_KMS_KEY=alias/onyx-secrets-key
PREFIX=/onyx/prod/secrets

POSTGRES_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
DB_READONLY_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
MINIO_SECRET="$(openssl rand -base64 32 | tr -d '\n')"

aws ssm put-parameter \
  --name "$PREFIX/POSTGRES_PASSWORD" \
  --type SecureString \
  --key-id "$SSM_KMS_KEY" \
  --value "$POSTGRES_PASSWORD" \
  --region "$REGION"

aws ssm put-parameter \
  --name "$PREFIX/DB_READONLY_PASSWORD" \
  --type SecureString \
  --key-id "$SSM_KMS_KEY" \
  --value "$DB_READONLY_PASSWORD" \
  --region "$REGION"

aws ssm put-parameter \
  --name "$PREFIX/MINIO_ROOT_PASSWORD" \
  --type SecureString \
  --key-id "$SSM_KMS_KEY" \
  --value "$MINIO_SECRET" \
  --region "$REGION"

aws ssm put-parameter \
  --name "$PREFIX/S3_AWS_SECRET_ACCESS_KEY" \
  --type SecureString \
  --key-id "$SSM_KMS_KEY" \
  --value "$MINIO_SECRET" \
  --region "$REGION"
```

Optional secrets for this deployment shape:

| SSM parameter | Needed when |
|---------------|-------------|
| `/onyx/prod/secrets/GEN_AI_API_KEY` | pre-configuring a default LLM API key through env |
| `/onyx/prod/secrets/DISCORD_BOT_TOKEN` | enabling the Discord bot |
| `/onyx/prod/secrets/ENCRYPTION_KEY_SECRET` | migrating old AES-CBC encrypted DB secrets |

Secrets intentionally **not** used in this guide:

| Secret | Why omitted |
|--------|-------------|
| `GOOGLE_OAUTH_CLIENT_SECRET` | no Google OAuth |
| `OAUTH_CLIENT_SECRET` | no OIDC |
| `SMTP_PASS` | no email verification |
| `USER_AUTH_SECRET` | not required for default `AUTH_BACKEND=redis` + `AUTH_TYPE=basic` without OAuth / reset / verification flows |

Important:

- `MINIO_ROOT_PASSWORD` and `S3_AWS_SECRET_ACCESS_KEY` must be identical when using the default MinIO-backed file store.
- you only need to create the optional SSM parameters you actually use.
- `bootstrap-env.sh` fetches every page under the prefix, so paths with more than 10 parameters are handled correctly.
- SSM values are written into `.env` using Docker Compose-safe quoting, so literal `$`, quotes, and multi-line values survive intact.
- if a key exists in both `env.config` and SSM, the SSM value wins in the generated `.env`

### 4e. Generate the DEK for database secret encryption

```bash
REGION=us-east-2
KMS_KEY_ID=<your-kms-key-id>
SSM_KMS_KEY=alias/onyx-secrets-key

ENCRYPTED_DEK_B64="$(aws kms generate-data-key \
  --key-id "$KMS_KEY_ID" \
  --key-spec AES_256 \
  --query CiphertextBlob \
  --output text \
  --region "$REGION")"

aws ssm put-parameter \
  --name "/onyx/prod/encrypted_dek/v1" \
  --type SecureString \
  --key-id "$SSM_KMS_KEY" \
  --value "$ENCRYPTED_DEK_B64" \
  --overwrite \
  --region "$REGION"

aws ssm get-parameter \
  --name "/onyx/prod/encrypted_dek/v1" \
  --with-decryption \
  --region "$REGION" \
  --query "Parameter.Name" \
  --output text
```

The last command should print `/onyx/prod/encrypted_dek/v1`.

---

## 5. EC2 Host Setup

### 5a. Install packages

Amazon Linux 2023 includes AWS CLI v2 by default. Verify it, then install the remaining packages the bootstrap script needs:

```bash
aws --version
python3 --version

sudo yum update -y
sudo yum install -y docker git jq python3
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

docker compose version
```

Log out and back in after adding `ec2-user` to the `docker` group.

### 5b. Clone the repo

```bash
cd /home/ec2-user
git clone --depth 1 https://github.com/onyx-dot-app/onyx.git
cd /home/ec2-user/onyx/deployment/docker_compose
```

### 5c. Create `env.config` from the repo template

```bash
cp env.ec2.cloudflare.template env.config
```

Edit `env.config`. Use the template variables as follows:

| Variable | Set / keep | Notes |
|----------|------------|-------|
| `IMAGE_TAG` | set if you want a pinned release | leave `latest` only if you are comfortable pulling the newest image on update |
| `WEB_DOMAIN` | set | public Cloudflare hostname, e.g. `https://onyx.company.com` |
| `AUTH_TYPE` | keep `basic` | this guide does not use OAuth or OIDC |
| `VALID_EMAIL_DOMAINS` | set | restrict Onyx self-signup to your real email domain list |
| `SESSION_EXPIRE_TIME_SECONDS` | keep or tune | default `604800` is a 7-day session lifetime |
| `LICENSE_ENFORCEMENT_ENABLED` | keep `false` | prevents EE/license-gated codepaths from loading for this MIT-only deployment |
| `POSTGRES_USER` | keep unless you have a reason to change it | database superuser name used by the compose stack |
| `DB_READONLY_USER` | keep unless you have a reason to change it | readonly DB username created by the stack |
| `FILE_STORE_BACKEND` | keep `s3` | this path uses MinIO as the S3-compatible object store |
| `S3_ENDPOINT_URL` | keep `http://minio:9000` | internal MinIO endpoint inside Docker |
| `S3_FILE_STORE_BUCKET_NAME` | keep or rename | bucket name created and used by MinIO |
| `S3_AWS_ACCESS_KEY_ID` | keep unless you deliberately change MinIO user names | must match `MINIO_ROOT_USER` in this default MinIO setup |
| `MINIO_ROOT_USER` | keep unless you deliberately change MinIO user names | must match `S3_AWS_ACCESS_KEY_ID` in this default MinIO setup |
| `AWS_REGION_NAME` | keep `us-east-2` | all AWS resources in this guide assume `us-east-2` |
| `AWS_SSM_SECRETS_PREFIX` | keep unless you intentionally chose another prefix | default `/onyx/prod/secrets` in SSM |
| `SECRET_ENCRYPTION_MODE` | keep `aws_kms_envelope` | required for KMS-backed DB secret encryption |
| `SECRET_ENCRYPTION_REQUIRED` | keep `true` | prevents falling back to plaintext DB-stored secrets |
| `AWS_KMS_KEY_ID` | set | UUID or ARN of the customer-managed KMS key you created in `us-east-2` |
| `AWS_ENCRYPTED_DEK_PARAM` | keep unless you intentionally changed the DEK SSM path pattern | default `/onyx/prod/encrypted_dek/v{version}` |
| `SECRET_KEY_VERSION` | keep `1` for new installs | bump during future DEK rotation |
| `SECRET_OLD_KEY_VERSIONS` | leave empty for new installs | populate only during DEK rotation or migration |
| `ENCRYPTION_KEY_SECRET` | leave commented out unless migrating old AES-CBC secrets | if needed, store it in SSM instead of writing it directly in `env.config` |
| `LOG_LEVEL` | keep or tune | default `info` is appropriate for normal production use |
| `SHOW_EXTRA_CONNECTORS` | keep `false` unless you intentionally want them visible | UI-only feature exposure flag |
| `TUNNEL_ORIGIN_PORT` | keep `8080` unless that host port conflicts | `cloudflared` should point to `http://localhost:8080` |

For a normal fresh deployment, the only values you usually need to change are:

- `WEB_DOMAIN`
- `VALID_EMAIL_DOMAINS`
- `AWS_KMS_KEY_ID`
- optionally `IMAGE_TAG`
- optionally `S3_FILE_STORE_BUCKET_NAME`
- optionally `TUNNEL_ORIGIN_PORT`

### 5d. Generate `.env` from SSM

```bash
chmod +x bootstrap-env.sh
./bootstrap-env.sh
```

Sanity-check the result:

```bash
grep '^AWS_REGION_NAME=' .env
grep '^SECRET_ENCRYPTION_MODE=' .env
grep '^POSTGRES_PASSWORD=' .env
grep '^MINIO_ROOT_PASSWORD=' .env
```

`.env` should now contain:

- the non-secret values from `env.config`
- the secret values fetched from SSM
- one effective value per key, with SSM overriding any duplicate key from `env.config`

The bootstrap script will:

- page through `GetParametersByPath` results until `NextToken` is exhausted
- fail fast if two SSM parameter names collapse to the same final env key
- quote secret values for Docker Compose so special characters and multi-line values remain valid

### 5e. Install the systemd unit from the repo

The repo includes a tunnel-specific unit file that:

- runs the bootstrap script before startup
- starts `docker-compose.prod-tunnel.yml`
- restarts in step with `docker.service` via `PartOf=docker.service`
- runs as `ec2-user` with access to the Docker group

```bash
sudo install -m 0644 onyx.service.tunnel /etc/systemd/system/onyx.service
sudo systemctl daemon-reload
sudo systemctl enable onyx.service
```

If you cloned the repo somewhere other than `/home/ec2-user/onyx`, edit `/etc/systemd/system/onyx.service` before enabling it.

### 5f. Start Onyx

```bash
sudo systemctl start onyx.service
sudo systemctl status onyx.service
```

Verify locally on the instance:

```bash
curl http://127.0.0.1:8080/api/health
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack ps
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack logs api_server -f --tail=50
journalctl -u onyx.service --no-pager -n 50
```

The origin should be listening only on localhost:

```bash
ss -ltnp | grep 8080
```

Vespa is no longer published on host ports in the tunnel compose file. If you need to inspect it, do it from inside the Docker network:

```bash
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack exec -T index \
  curl -fsS http://localhost:8081/state/v1/health
```

---

## 6. Cloudflare Tunnel

This repo does not install `cloudflared`, but the expected origin for the tunnel is:

```yaml
ingress:
  - hostname: onyx.company.com
    service: http://localhost:8080
  - service: http_status:404
```

Because nginx is bound to `127.0.0.1:${TUNNEL_ORIGIN_PORT}`, you do not need public inbound `80/443` on the EC2 security group.

Cloudflare Access should sit in front of that hostname. After Access allows the request through, the user still signs into Onyx itself with a normal Onyx account.

The first Onyx user to register becomes the Onyx admin.

---

## 7. Migrating Existing Encrypted Secrets

Skip this section for a fresh install.

If an older deployment used legacy AES-CBC encrypted secrets, keep the old `ENCRYPTION_KEY_SECRET` available during migration:

1. store it in SSM as `/onyx/prod/secrets/ENCRYPTION_KEY_SECRET`
2. rerun `./bootstrap-env.sh` or restart `onyx.service`
3. run the re-encryption command

Dry run:

```bash
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack exec -T api_server \
  python -m onyx.db.reencrypt_secret_values
```

Apply:

```bash
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack exec -T api_server \
  python -m onyx.db.reencrypt_secret_values --apply
```

Restart the app containers after the apply run:

```bash
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack restart api_server background
```

After every legacy secret has been re-encrypted successfully, you can remove `ENCRYPTION_KEY_SECRET` from SSM if you no longer need legacy fallback.

---

## 8. Rotation

### Rotate an `.env` secret

Example for `POSTGRES_PASSWORD`:

```bash
aws ssm put-parameter \
  --name "/onyx/prod/secrets/POSTGRES_PASSWORD" \
  --type SecureString \
  --key-id alias/onyx-secrets-key \
  --value "new-strong-password" \
  --overwrite \
  --region us-east-2

docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack exec -T relational_db \
  psql -U postgres -c "ALTER USER postgres PASSWORD 'new-strong-password';"

sudo systemctl restart onyx.service
```

### Rotate the KMS envelope key version

```bash
REGION=us-east-2
KMS_KEY_ID=<your-kms-key-id>

ENCRYPTED_DEK_B64="$(aws kms generate-data-key \
  --key-id "$KMS_KEY_ID" \
  --key-spec AES_256 \
  --query CiphertextBlob \
  --output text \
  --region "$REGION")"

aws ssm put-parameter \
  --name "/onyx/prod/encrypted_dek/v2" \
  --type SecureString \
  --key-id alias/onyx-secrets-key \
  --value "$ENCRYPTED_DEK_B64" \
  --overwrite \
  --region "$REGION"
```

Then update `env.config`:

```dotenv
SECRET_KEY_VERSION=2
SECRET_OLD_KEY_VERSIONS=1
```

Restart and re-encrypt:

```bash
sudo systemctl restart onyx.service

docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack exec -T api_server \
  python -m onyx.db.reencrypt_secret_values --apply
```

---

## 9. Operations

Restart the stack and re-fetch SSM secrets:

```bash
sudo systemctl restart onyx.service
```

View bootstrap / startup logs:

```bash
journalctl -u onyx.service --no-pager -n 100
```

View container logs:

```bash
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack logs <service> -f --tail=100
```

Update Onyx:

```bash
cd /home/ec2-user/onyx
git pull
cd deployment/docker_compose
sudo systemctl restart onyx.service
```

Database backup:

```bash
docker exec onyx-stack-relational_db-1 pg_dump -U postgres -d postgres > backup-$(date +%Y%m%d).sql
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `AccessDeniedException` on SSM or KMS | IMDS hop limit still `1` | set hop limit to `2` |
| `AccessDeniedException` on SSM or KMS | role policy or key policy points at the wrong region or key ARN | confirm everything is in `us-east-2` and the policy references the correct key |
| bootstrap logs show `0 secret(s)` | wrong SSM prefix | verify `/onyx/prod/secrets` exists in `us-east-2` |
| `Failed to fetch encrypted DEK from AWS SSM Parameter Store` | wrong `AWS_ENCRYPTED_DEK_PARAM` or missing IAM permission | verify `/onyx/prod/encrypted_dek/v1` exists and the instance role can read it |
| `Failed to decrypt DEK with AWS KMS` | wrong `AWS_KMS_KEY_ID`, key policy, or region | verify the CMK and instance role permissions |
| `Cannot decrypt legacy AES-CBC data: ENCRYPTION_KEY_SECRET is not set` | migration needs the old key | store `ENCRYPTION_KEY_SECRET` in SSM before re-encrypting |
| bootstrap fails with a duplicate SSM key error | two parameter paths end with the same env key name | rename one of the SSM parameters so every final path segment is unique |
| Cloudflare Tunnel cannot connect to origin | wrong origin port or Onyx not running | verify `curl http://127.0.0.1:8080/api/health` on the instance |
| `502 Bad Gateway` from nginx | api/web container not healthy yet | check `docker compose ... logs api_server web_server` |

Useful manual checks:

```bash
aws ssm get-parameters-by-path \
  --path /onyx/prod/secrets \
  --with-decryption \
  --region us-east-2

aws ssm get-parameter \
  --name /onyx/prod/encrypted_dek/v1 \
  --with-decryption \
  --region us-east-2

docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack ps
docker compose -f docker-compose.prod-tunnel.yml -p onyx-stack logs api_server --tail=100
```

---

## 11. Architecture

```text
Cloudflare Access
        |
Cloudflare Tunnel
        |
http://127.0.0.1:8080
        |
      nginx
     /     \
 web_server  api_server
                |
        PostgreSQL / Redis / Vespa / MinIO

AWS SSM Parameter Store
  - /onyx/prod/secrets/*
  - /onyx/prod/encrypted_dek/v*

AWS KMS (us-east-2)
  - CMK for SecureString at-rest encryption
  - decrypts wrapped DEK for DB secret encryption
```

Boot sequence:

1. EC2 starts
2. systemd starts `onyx.service`
3. `bootstrap-env.sh` fetches SSM secrets into `.env`
4. `docker-compose.prod-tunnel.yml` starts the Onyx stack
5. `api_server` and `background` fetch `/onyx/prod/encrypted_dek/v{version}` from SSM
6. KMS decrypts the DEK
7. Onyx uses that DEK for database credential encryption at runtime
