# Callus-Bridge 常用任务。
#
# gRPC 契约与现用 WeJam bridge 线兼容（wejam.v1）。默认端口 7701，避免与 wejam-session 冲突。

SHELL := /bin/bash
PYTHON ?= .venv/bin/python
NAME ?= callus-session
IMAGE ?= callus/wechat:latest

.DEFAULT_GOAL := help
.PHONY: help proto proto-check build up down logs shell status test clean openclaw openclaw-status

help:  ## 显示所有可用任务
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

proto:  ## 从 proto 重新生成 gRPC stub
	bash scripts/gen-proto.sh

proto-check:  ## 校验生成的 stub 是否与 proto 同步
	bash scripts/gen-proto.sh --check

build:  ## 构建 Callus 微信镜像
	docker build -f docker/Dockerfile -t $(IMAGE) .

up:  ## 启动 Callus 会话容器（默认 127.0.0.1:7701）
	bash docker/run.sh

down:  ## 停止并删除容器（不动状态卷）
	docker rm -f $(NAME)

logs:  ## 跟随容器日志
	docker logs -f $(NAME)

shell:  ## 进入容器
	docker exec -it $(NAME) bash

status:  ## 查看 GUI 桥服务与微信状态（:7701）
	WEJAM_TARGET=127.0.0.1:7701 $(PYTHON) -m wejam.cli status

openclaw:  ## 启动非 GUI openclaw 桥（默认 :7702，无 Xvfb/微信）
	bash scripts/run-openclaw.sh

openclaw-status:  ## 查看 openclaw 桥状态（:7702）
	WEJAM_TARGET=127.0.0.1:7702 $(PYTHON) -m wejam.cli status

test:  ## 离线单测
	$(PYTHON) -m pytest tests/ -q

clean:  ## 清理缓存
	find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
