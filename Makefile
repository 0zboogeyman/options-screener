.PHONY: build up down restart logs status etl backup clean help

# 本目录即单容器部署项目根，相对卷路径直接指向 ./data。
COMPOSE := docker compose

help:
	@echo "单容器部署目标："
	@echo "  make build    构建合并镜像"
	@echo "  make up       构建并启动单容器"
	@echo "  make down     停止单容器"
	@echo "  make restart  重启单容器"
	@echo "  make logs     实时日志（uvicorn + node 交错输出）"
	@echo "  make status   容器状态 + 双端口健康检查"
	@echo "  make etl      在运行中的容器内执行每日 ETL"
	@echo "  make backup   备份 data 目录（保留 7 天）"
	@echo "  make clean    停止并删除容器与卷"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down && $(COMPOSE) up -d

logs:
	$(COMPOSE) logs -f --tail=100

status:
	@echo "=== 容器状态 ==="
	@$(COMPOSE) ps
	@echo ""
	@echo "=== 后端健康 (3115) ==="
	@curl -s http://localhost:3115/api/health || echo "unreachable"
	@echo ""
	@echo "=== 前端 (3116) ==="
	@curl -sI http://localhost:3116/ | head -n 1 || echo "unreachable"
	@echo ""

etl:
	docker exec spread-backend python /app/scripts/etl_daily.py

backup:
	@echo "备份 spread-data 卷..."
	@mkdir -p ./backups
	docker run --rm -v spread-data:/data -v "$$(pwd)":/backup alpine \
		tar czf "/backup/data-$$(date +%Y%m%d-%H%M%S).tar.gz" -C /data .
	@echo "清理超过 7 天的旧备份..."
	find ./backups -name "data-*.tar.gz" -mtime +7 -delete 2>/dev/null || true
	@echo "备份完成。"

clean:
	$(COMPOSE) down -v
