# Agentic Zerodha Platform (Django)

Full-stack backend foundation for an agentic Zerodha trading platform with:
- Zerodha (Kite Connect) integration boundaries
- OpenRouter key management
- Agent configuration and scheduling
- Human-in-loop approvals (dashboard/admin/telegram-ready)
- Multi-approver RBAC (owner + assigned approvers with quorum)
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
- `GET /api/v1/approval-requests/queue/`
- `POST /api/v1/approval-requests/{id}/decide/`
- `GET/POST /api/v1/broker-credentials/`
- `GET/POST /api/v1/llm-credentials/`
- `POST /api/v1/telegram/webhook/{TELEGRAM_WEBHOOK_SECRET}/`

## Telegram Approval Setup

1. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` in `.env`.
2. Link each user profile with a `telegram_chat_id` (Django admin).
3. Set agent config `approval_channels` to include `"telegram"`.
4. Optional timeout policy in agent config:
   - `"timeout_policy": "auto_reject" | "auto_pause" | "escalate"`
   - `"escalation_grace_minutes": 15` (used when policy is `"escalate"`)
5. Configure Telegram webhook to:
   `https://<your-domain>/api/v1/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>/`
6. Include Telegram secret header validation using:
   `X-Telegram-Bot-Api-Secret-Token: <TELEGRAM_WEBHOOK_SECRET>`

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
