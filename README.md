# MOE Classification Service

A self-contained FastAPI microservice for multilingual text classification using a Mixture of Experts (MoE) routing system.

## Architecture

```
Input Text → Language Detection → Domain Classification → Task Routing → Expert Execution → Result
              (FastText)          (XLM-RoBERTa)          (Q-Learning)    (LoRA Adapters)
```

**Supported Tasks (Finance Domain):**
- Sentiment Analysis (rating 1-5) — 6 languages
- PII Extraction — 7 languages
- News Classification — 5 languages
- ESCI Product Relevance — 3 languages

## Quick Start

### 1. Clone and setup

```bash
git clone https://github.com/Multilingual-LLMs-for-Classification/moe-classification-service.git
cd moe-classification-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Download model weights

```bash
# From an existing moe-router installation:
./scripts/download_models.sh --source /path/to/moe-router

# Or manually place weights (see models/README.md for details)
```

### 3. Run the service

```bash
cp .env.example .env  # Edit as needed
./scripts/run.sh
```

The service starts at `http://localhost:8000`

### 4. Docker deployment

```bash
cd docker
docker-compose up --build
```

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register a new user |
| POST | `/api/v1/auth/token` | Get JWT access token |

### Classification (Requires Auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/classify` | Classify single text |
| POST | `/api/v1/classify/batch` | Classify multiple texts |
| GET | `/api/v1/classify/stats` | Get system statistics |

### Health Checks

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Basic health check |
| GET | `/api/v1/health/ready` | Readiness check (models loaded) |
| GET | `/api/v1/health/live` | Liveness check |

## Usage Example

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "password": "mypassword123"}'

# Get token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=myuser&password=mypassword123" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Classify
curl -X POST http://localhost:8000/api/v1/classify \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Rate this product review from 1 to 5 stars based on sentiment.",
    "input_data": {
      "text": "This product is amazing! Best purchase ever!",
      "title": "Excellent product"
    },
    "options": {"return_probabilities": true}
  }'
```

## Project Structure

```
moe-classification-service/
├── app/                          # FastAPI service layer
│   ├── main.py                   # Application entry point
│   ├── config.py                 # Configuration settings
│   ├── dependencies.py           # Dependency injection
│   ├── middleware/                # Error handling middleware
│   ├── routers/                  # API endpoint routers
│   ├── schemas/                  # Pydantic request/response models
│   └── services/                 # Business logic services
├── moe_router/                   # Core MoE routing package
│   ├── gating/                   # Routing components
│   │   ├── components/           # Language, domain, task classifiers
│   │   └── models/               # Trained gating model weights
│   ├── experts/                  # Expert implementations
│   │   ├── config/               # Expert registry configuration
│   │   ├── llms/                 # LLM adapter pool & task experts
│   │   └── util/                 # Domain/task loading utilities
│   └── models/                   # Language detection model
├── docker/                       # Docker configuration
├── scripts/                      # Operational scripts
├── tests/                        # Test suite
├── models/                       # Model weights documentation
├── .github/workflows/            # CI pipeline
├── requirements.txt
├── .env.example
└── README.md
```

## Configuration

Copy `.env.example` to `.env` and customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | API host address |
| `API_PORT` | `8000` | API port |
| `DEBUG` | `false` | Enable debug mode with auto-reload |
| `JWT_SECRET_KEY` | (random) | Secret key for JWT tokens |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token expiration time |
| `CUDA_VISIBLE_DEVICES` | `0` | GPU device index |
| `REQUEST_TIMEOUT_SECONDS` | `120` | Classification timeout |

## API Documentation

Once the service is running:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Prerequisites

- Python 3.11+
- CUDA-capable GPU (recommended)
- Model weights (see `models/README.md`)

## License

MIT
