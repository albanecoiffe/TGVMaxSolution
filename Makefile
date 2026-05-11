.PHONY: help install backend run test test-api test-planner refresh

help:
	@echo "Cibles disponibles :"
	@echo "  make install       - installe les dependances"
	@echo "  make backend       - lance le backend FastAPI en mode reload"
	@echo "  make run           - alias de make backend"
	@echo "  make test          - lance toute la suite de tests"
	@echo "  make test-api      - lance les tests API"
	@echo "  make test-planner  - lance les tests du planner"
	@echo "  make refresh       - appelle l'endpoint de refresh local"

install:
	uv sync

backend:
	uv run uvicorn app.main:app --reload

run: backend

test:
	PYTHONPATH=. uv run pytest

test-api:
	PYTHONPATH=. uv run pytest tests/test_api.py

test-planner:
	PYTHONPATH=. uv run pytest tests/test_planner.py

refresh:
	curl -X POST http://127.0.0.1:8000/api/refresh
