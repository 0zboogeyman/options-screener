.PHONY: build up down restart logs status etl backup deploy clean

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose down && docker compose up -d

logs:
	docker compose logs -f --tail=100

status:
	@echo "=== Container Status ==="
	@docker compose ps
	@echo ""
	@echo "=== Backend Health ==="
	@curl -s http://localhost:3115/api/health || echo "Backend unreachable"
	@echo ""

etl:
	docker exec spread-backend python /app/scripts/etl_daily.py

backup:
	@echo "Backing up data directory..."
	@mkdir -p ./backups
	tar czf "./backups/data-$(shell date +%%Y%%m%%d-%%H%%M%%S).tar.gz" ./data
	@echo "Backup complete."
	@echo ""
	@echo "Cleaning old backups (>$(BACKUP_RETENTION)d)..."
	find ./backups -name "data-*.tar.gz" -mtime +7 -delete
	@echo "Backup rotation complete."

deploy:
	@echo "=== Building images ==="
	docker compose build
	@echo "=== Starting services ==="
	docker compose up -d
	@echo "=== Waiting for backend healthy ==="
	@for i in $$(seq 1 30); do \
		if curl -sf http://localhost:3115/api/health > /dev/null 2>&1; then \
			echo "Backend healthy after $$i seconds"; \
			break; \
		fi; \
		sleep 2; \
	done
	@echo "=== Checking data ==="
	@docker exec spread-backend python -c "from app.services.loader import list_available_dates; print(list_available_dates())" 2>/dev/null || echo "No data yet, run 'make etl'"
	@echo "=== Deploy complete ==="

clean:
	docker compose down -v
	docker system prune -f
