# MOE Classification Service

A self-contained FastAPI microservice for multilingual text classification using a
Mixture of Experts (MoE) routing system. Users are authenticated via JWT tokens and
credentials are stored in a hosted **Supabase PostgreSQL** database shared across all
distributed service instances.

---

## Architecture

```
Input Text
    │
    ▼
┌─────────────────────────────────────────────┐
│              GATING PIPELINE                │
│                                             │
│  1. Language Detection   (FastText)         │
│  2. Domain Classification (XLM-RoBERTa)    │
│  3. Task Routing          (Q-Learning)      │
│  4. Expert Lookup         (Registry)        │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│              EXPERT EXECUTION               │
│  LoRA Adapter loaded on base LLM            │
│  (LRU pool — models swapped per task)       │
└─────────────────────────────────────────────┘
                       │
                       ▼
                   Result
```

**Supported Tasks (Finance Domain):**

| Task | Languages |
|------|-----------|
| Sentiment Analysis (rating 1–5) | EN, DE, FR, ES, JA, ZH |
| PII Extraction | EN, NL, FR, DE, IT, ES, SV |
| News Classification | EN, DA, ES, PL, TR |
| ESCI Product Relevance (E/S/C/I) | EN, JA, ES |

---

## File Structure

```
moe-classification-service/
├── app/                          # FastAPI service layer
│   ├── main.py                   # Entry point — runs create_tables() + routing init
│   ├── config.py                 # Settings (DATABASE_URL, JWT, GPU …)
│   ├── db.py                     # SQLAlchemy engine, UserRecord model, get_db()
│   ├── dependencies.py           # DI: auth, routing service
│   ├── middleware/               # Error handling, request ID
│   ├── routers/                  # auth, classify, health, admin, analytics
│   ├── schemas/                  # Pydantic request/response models
│   └── services/
│       ├── auth_service.py       # JWT + bcrypt + DB-backed user CRUD
│       ├── routing_service.py    # MoE pipeline orchestration
│       ├── analytics_service.py
│       └── config_service.py
├── moe_router/                   # Core MoE routing package
│   ├── gating/
│   │   ├── components/           # Language detector, domain classifier, Q-router
│   │   └── models/               # Trained gating model weights
│   └── experts/
│       ├── config/               # experts_registry.json
│       └── llms/                 # LRU expert pool + LoRA adapters
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── volumes/
│       ├── gating_models/        # XLM-RoBERTa + Q-learning weights
│       ├── language_models/      # FastText lid.176.bin
│       ├── adapter_weights/      # LoRA adapters per expert
│       └── db/                   # SQLite users.db (auto-created on first run)
├── scripts/
│   ├── run.sh                    # Local run helper
│   └── download_models.sh        # Model weight downloader
├── tests/
├── .env.example
└── requirements.txt
```

---

## Prerequisites

- Python 3.11+
- CUDA-capable GPU (recommended; CPU works but inference is slow)
- Model weights (see `models/README.md`)

---

## Setup — Step 1: Create a Supabase Project

1. Go to [supabase.com](https://supabase.com) and create a free account
2. Click **New Project** — choose a name, set a strong database password, pick a region
3. Wait ~2 minutes for the project to provision
4. Go to **Project Settings → Database → Connection string → URI**
5. Copy the **Session mode** connection string (port `5432`):

```
postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

> The `users` table is created automatically on first service startup — no manual SQL needed.

---

## Setup — Option A: Run Directly (Development / Frontend Testing)

### Step 1 — Install dependencies

```bash
cd /home/cse/Desktop/moe-classification-service
pip install -r requirements.txt
```

### Step 2 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your Supabase connection string:

```dotenv
JWT_SECRET_KEY=any-local-dev-secret
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

### Step 3 — Start the service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

The service starts at `http://localhost:8000`.

**What happens on startup:**
- Connects to Supabase and creates the `users` table if it doesn't exist (instant)
- Gating models load (FastText + XLM-RoBERTa + Q-learning, ~1–2 min)
- If model weights are missing, a warning is printed but the service still starts —
  auth and health endpoints work; `/classify` returns an error until models are present

---

## Setup — Option B: Docker

### Step 1 — Set the Supabase connection string in docker-compose

Open [docker/docker-compose.yml](docker/docker-compose.yml) and replace the placeholder:

```yaml
- DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

### Step 2 — Place model weights

```
docker/volumes/
├── gating_models/
│   ├── domain_xlmr/              # XLM-RoBERTa domain classifier weights
│   └── task_routers_qlearning/   # Q-learning task router weights
├── language_models/
│   └── lid.176.bin               # FastText language ID model
└── adapter_weights/              # LoRA adapters
    └── finance/
        ├── sentiment_analysis/
        ├── pii/
        ├── news_classification/
        └── esci/
```

### Step 3 — Build and start

```bash
cd /home/cse/Desktop/moe-classification-service/docker
docker-compose up --build -d
```

**What happens:**
- Connects to Supabase and creates the `users` table if it doesn't exist
- Service becomes ready at `http://localhost:8000`

### Step 4 — Watch startup logs

```bash
docker-compose logs -f
```

### Step 5 — Verify the service is ready

```bash
curl http://localhost:8000/api/v1/health/ready
```

### Stop / rebuild

```bash
# Stop
docker-compose down

# Rebuild after code changes
docker-compose up --build -d
```

---

## Authentication

The service uses **JWT Bearer tokens**. All `/api/v1/classify` endpoints require authentication.
Credentials are stored in SQLite with bcrypt-hashed passwords.

### Register a user

**Endpoint:** `POST /api/v1/auth/register`
**Body format:** raw JSON

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "securepassword123"}'
```

**Response (201):**
```json
{"username": "alice", "disabled": false}
```

**In Postman:** Body → raw → JSON

---

### Login and get a token

**Endpoint:** `POST /api/v1/auth/token`
**Body format:** `x-www-form-urlencoded` — JSON is **not** accepted here (OAuth2 requirement)

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=alice&password=securepassword123"
```

**Response (200):**
```json
{"access_token": "eyJ...", "token_type": "bearer"}
```

**In Postman:** Body → x-www-form-urlencoded → add keys `username` and `password`

---

### Use the token

Add the token to all subsequent requests via the `Authorization` header:

```bash
TOKEN="eyJ..."

curl -X POST http://localhost:8000/api/v1/classify \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Revenue increased by 20%.", "description": "Classify sentiment 1-5."}'
```

Tokens expire after **30 minutes** (configurable via `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`).

---

## End-to-End Usage Example

```bash
# 1. Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "securepassword123"}'

# 2. Login — capture token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=alice&password=securepassword123" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 3. Classify
curl -X POST http://localhost:8000/api/v1/classify \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Revenue increased by 20% year over year, exceeding analyst expectations.",
    "description": "Classify the sentiment of this financial statement on a scale of 1-5."
  }'
```

**Expected response:**
```json
{
  "request_id": "...",
  "language": "english",
  "domain": "finance",
  "task": "rating",
  "result": "4",
  "confidence": 0.91,
  "processing_time_ms": 350.2
}
```

---

## User Management

Users are stored in your **Supabase PostgreSQL** database and are accessible from all
service instances (coordinator, workers, local dev) simultaneously.

### Inspect users — Supabase Dashboard

1. Open your project at [supabase.com](https://supabase.com)
2. Go to **Table Editor** → `users` table
3. Browse, filter, and edit rows directly in the UI

Or use the **SQL Editor**:
```sql
SELECT id, username, disabled FROM users;
```

### Register via the API (normal flow)

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "securepassword123"}'
```

### Pre-seed an admin account

```bash
# Running service
docker exec -it moe-classification-service python3 - <<'EOF'
from app.db import SessionLocal, create_tables
from app.services.auth_service import create_user

create_tables()
db = SessionLocal()
create_user(db, "admin", "securepassword123")
db.close()
print("Done")
EOF
```

Or directly via Supabase SQL Editor:
```sql
-- You need a bcrypt hash — generate one first:
-- python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('securepassword123'))"

INSERT INTO users (username, hashed_password, disabled)
VALUES ('admin', '$2b$12$...paste-hash-here...', false);
```

### Disable a user

Via Supabase SQL Editor:
```sql
UPDATE users SET disabled = true WHERE username = 'alice';
```

### Delete a user

Via Supabase SQL Editor:
```sql
DELETE FROM users WHERE username = 'alice';
```

---

## API Reference

### Authentication

| Method | Endpoint | Auth | Body format | Description |
|--------|----------|------|-------------|-------------|
| POST | `/api/v1/auth/register` | No | JSON | Register a new user |
| POST | `/api/v1/auth/token` | No | x-www-form-urlencoded | Get JWT access token |

### Classification

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/classify` | Bearer | Classify a single text |
| POST | `/api/v1/classify/batch` | Bearer | Classify multiple texts |
| GET | `/api/v1/classify/stats` | Bearer | System statistics |

**Request body (`POST /api/v1/classify`):**
```json
{
  "text": "The stock rose 15% after earnings.",
  "description": "Classify sentiment of this financial news (1-5 scale).",
  "options": {
    "return_probabilities": false,
    "return_raw_response": false
  }
}
```

### Health

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/health` | No | Basic alive check |
| GET | `/api/v1/health/ready` | No | Ready check (models loaded) |
| GET | `/api/v1/health/live` | No | Liveness probe |

### Interactive API Docs

| UI | URL |
|----|-----|
| Swagger | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/openapi.json |

---

## Configuration Reference

Copy `.env.example` to `.env` and set values:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | Bind address |
| `API_PORT` | `8000` | Listen port |
| `DEBUG` | `false` | Enable auto-reload |
| `JWT_SECRET_KEY` | (random) | JWT signing secret — **change in production** |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token lifetime in minutes |
| `CUDA_VISIBLE_DEVICES` | `0` | GPU index |
| `REQUEST_TIMEOUT_SECONDS` | `120` | Classification timeout |
| `MAX_CONCURRENT_GPU_REQUESTS` | `1` | GPU request concurrency |
| `DATABASE_URL` | — | Supabase PostgreSQL connection string (**required**) |

---

## Troubleshooting

### 400 on `/register` — "Username already registered"

The username already exists. Use a different one or delete the existing entry:

```bash
sqlite3 users.db "DELETE FROM users WHERE username='alice';"
```

### 401 on `/classify` — "Could not validate credentials"

JWT token has expired (default 30 min) or is invalid. Log in again to get a fresh token.

### Service starts but `/classify` returns an error

Gating model weights are missing. Check:

```bash
ls docker/volumes/gating_models/
ls docker/volumes/language_models/
```

`GET /api/v1/health/ready` returns `{"status": "not_ready"}` until models are loaded.

### Cannot connect to Supabase

- Check `DATABASE_URL` is set correctly in `.env` or `docker-compose.yml`
- Make sure you copied the **Session mode (port 5432)** string, not the transaction pooler
- Verify your Supabase project is active (free tier projects pause after 1 week of inactivity — unpause from the dashboard)

### Port 8000 already in use

```bash
sudo lsof -ti:8000 | xargs kill -9
```

---

## License

MIT
