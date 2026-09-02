.PHONY: help install test lint format run docker-up docker-down clean

help:
	@echo "Available commands:"
	@echo "  make install     Install production & development dependencies"
	@echo "  make test        Run full automated test suite"
	@echo "  make lint        Run ruff linter"
	@echo "  make format      Format code with ruff"
	@echo "  make run         Start local FastAPI development server"
	@echo "  make docker-up   Build and start containers via Docker Compose"
	@echo "  make docker-down Stop running containers"
	@echo "  make clean       Remove virtualenv, cache, and build artifacts"

install:
	uv pip install -e ".[dev]"

test:
	uv run pytest -v

lint:
	uv run ruff check app tests

format:
	uv run ruff format app tests

run:
	uv run uvicorn app.main:app --env-file .env --reload --port 8000

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} +
