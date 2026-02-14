# Agentic Zerodha Platform (Django)

Full-stack backend foundation for an agentic Zerodha trading platform with:
- Zerodha (Kite Connect) integration boundaries
- OpenRouter key management
- Agent configuration and scheduling
- Human-in-loop approvals (dashboard/admin/telegram-ready)
- Risk checks and audited execution pipeline

## Stack

- Python 3.12
- Django + DRF
- Celery + Redis
- Postgres
- Docker Compose
- uv for dependency and environment management

## Quick Start (Local)

1. Prepare environment:
```bash
cp .env.example .env
uv sync --group dev
```

2. Run database and cache:
```bash
docker compose up -d postgres redis
```

3. Run migrations and start app:
```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

4. Start workers (separate terminals):
```bash
uv run celery -A config worker --loglevel=info
uv run celery -A config beat --loglevel=info
```

## Quick Start (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

## API

- `GET /health/`
- `GET/POST /api/v1/agents/`
- `GET /api/v1/approval-requests/`
- `POST /api/v1/approval-requests/{id}/decide/`

## Project Structure

```text
src/
  config/
    settings/
  apps/
    accounts/
    credentials/
    broker_kite/
    agents/
    approvals/
    risk/
    execution/
    market_data/
    audit/
```

## Security Notes

- API keys/secrets are stored in encrypted fields placeholders; integrate KMS before production.
- Keep live trading behind approval and risk gates.
- Enable strict RBAC for approvals and operational actions.
