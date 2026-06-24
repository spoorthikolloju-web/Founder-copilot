.PHONY: install playground run test lint

install:
	uv sync

playground:
	uv run adk web app --host 127.0.0.1 --port 18081 --reload_agents

# run: requires GCP credentials (GOOGLE_CLOUD_PROJECT, ADC). Use 'make playground' for local dev.
run:
	uv run uvicorn app.agent_runtime_app:agent_runtime --host 127.0.0.1 --port 8080

test:
	uv run pytest tests/unit

test-integration:
	uv run pytest tests/integration -v

lint:
	uv run ruff check app
