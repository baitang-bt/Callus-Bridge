#!/bin/bash
# 启动 Callus-Bridge 会话容器。
#
# 与 WeJam 会话容器并列时可改端口；gRPC 契约仍是 wejam.v1，宿主换 TARGET 即可。
#
# 用法:
#   ./run.sh                     # 默认 127.0.0.1:7701
#   CALLUS_PORT=7700 ./run.sh    # 与旧 WeJam 同端口（勿与 wejam-session 同时占）
set -eu

NAME="${CALLUS_NAME:-callus-session}"
IMAGE="${CALLUS_IMAGE:-callus/wechat:latest}"
VOLUME="${CALLUS_VOLUME:-callus-data}"
PORT="${CALLUS_PORT:-7701}"

if [[ -z "${DOCKER_BIN:-}" ]]; then
    if command -v docker >/dev/null 2>&1; then
        DOCKER_BIN="$(command -v docker)"
    elif [[ -x "${HOME}/.local/bin/docker" ]]; then
        DOCKER_BIN="${HOME}/.local/bin/docker"
    elif [[ -x /usr/local/bin/docker ]]; then
        DOCKER_BIN=/usr/local/bin/docker
    elif [[ -x /Applications/Docker.app/Contents/Resources/bin/docker ]]; then
        DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
    else
        echo "docker: command not found" >&2
        exit 127
    fi
fi

"$DOCKER_BIN" rm -f "$NAME" >/dev/null 2>&1 || true
"$DOCKER_BIN" volume create "$VOLUME" >/dev/null

"$DOCKER_BIN" run -d --name "$NAME" \
    -p "127.0.0.1:${PORT}:7700" \
    -v "${VOLUME}:/data" \
    --restart unless-stopped \
    "$IMAGE"

echo "容器 $NAME 已启动"
echo "  gRPC   : 127.0.0.1:${PORT}  (wejam.v1 线兼容)"
echo "  状态卷 : ${VOLUME}"
echo
echo "客户端示例:"
echo "  WEJAM_TARGET=127.0.0.1:${PORT} python -m wejam.cli status"
