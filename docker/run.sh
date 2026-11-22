#!/bin/bash
# 启动 / 恢复 Callus-Bridge 会话容器。
#
# 已有容器只 docker start，不 rm，避免清掉 Linux 微信登录态。
#
# 用法:
#   ./run.sh
#   CALLUS_PORT=7700 ./run.sh
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

"$DOCKER_BIN" volume create "$VOLUME" >/dev/null

if "$DOCKER_BIN" inspect "$NAME" >/dev/null 2>&1; then
    state="$("$DOCKER_BIN" inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || echo false)"
    if [[ "$state" == "true" ]]; then
        echo "容器 $NAME 已在运行（保留登录态）"
    else
        echo "恢复已有容器 $NAME …"
        "$DOCKER_BIN" start "$NAME" >/dev/null
        echo "容器 $NAME 已启动（卷 $VOLUME，登录数据保留）"
    fi
else
    echo "创建新容器 $NAME …"
    "$DOCKER_BIN" run -d --name "$NAME" \
        -p "127.0.0.1:${PORT}:7700" \
        -v "${VOLUME}:/data" \
        --restart unless-stopped \
        "$IMAGE"
    echo "容器 $NAME 已创建并启动"
fi

echo "  gRPC   : 127.0.0.1:${PORT}  (wejam.v1 线兼容)"
echo "  状态卷 : ${VOLUME}"
echo
echo "客户端示例:"
echo "  WEJAM_TARGET=127.0.0.1:${PORT} python -m wejam.cli status"
