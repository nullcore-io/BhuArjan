# BhuArjan — single-command demo (Docs/Backend.md §11)
COMPOSE = docker compose -f infra/docker-compose.yml

demo: ## build + start everything, seed on first boot
	$(COMPOSE) up -d --build
	@echo "web:   http://localhost:3016"
	@echo "api:   http://localhost:8016/api/v1/docs"
	@echo "minio: http://localhost:9101 (bhuarjan / bhuarjan_dev)"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

destroy:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f --tail=100

dev-infra: ## db + minio only; run api/web locally
	$(COMPOSE) up -d db minio

api-dev:
	cd api && uvicorn app.main:app --reload --port 8016

web-dev:
	cd web && npm run dev

test:
	cd api && python -m pytest tests -q

.PHONY: demo up down destroy logs dev-infra api-dev web-dev test
