.PHONY: bootstrap migrate makemigrations run worker beat test lint format docker-up docker-down

bootstrap:
	uv sync --group dev

makemigrations:
	uv run python manage.py makemigrations

migrate:
	uv run python manage.py migrate

run:
	uv run python manage.py runserver

worker:
	uv run celery -A config worker --loglevel=info

beat:
	uv run celery -A config beat --loglevel=info

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run mypy src

format:
	uv run ruff check . --fix

docker-up:
	docker compose up --build

docker-down:
	docker compose down
