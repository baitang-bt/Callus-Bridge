# Callus-Bridge

微信 **数据桥**（无 AI 大脑）。仓库：[baitang-bt/Callus-Bridge](https://github.com/baitang-bt/Callus-Bridge)。

与 WeJamBot 使用的 bridge **线兼容**：`package wejam.v1` / `service WeJam`。宿主把 `WEJAM_TARGET` 指到对应端口即可换桥。

本仓从 WeJam bridge 侧拷贝后演进，不修改 WeJamBot 仓内的 `agent/`。

## 两条路径

| 路径 | 端口 | 实现 | 说明 |
|------|------|------|------|
| **OpenClaw（推荐 / 非 GUI）** | **7702** | `python -m openclaw` | 腾讯 ilink 扫码 + 长轮询；**不起** Xvfb / Linux 微信 |
| GUI capture（遗留） | 7701 | Docker `callus-session` | AT-SPI + 滚动上下文 / 表情截取 |

字段映射与限制见 [docs/openclaw.md](docs/openclaw.md)。

## OpenClaw 快速开始（非 GUI）

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[openclaw]'
make openclaw                 # WEJAM_PORT=7702
# 另开终端：
make openclaw-status
WEJAM_TARGET=127.0.0.1:7702 .venv/bin/python -m wejam.cli   # 按 cli 子命令看 QR / watch
```

可选别名（白名单用人名时）：编辑 `data/openclaw/aliases.json`：

```json
{ "by_id": { "ilink_user_xxx": "白糖" } }
```

发送前该会话需要已有入站消息以取得 `context_token`（详见 openclaw 文档）。

## GUI 遗留路径

```bash
make build
make up          # 127.0.0.1:7701
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli status
```

| 能力 | 说明 |
|------|------|
| 既有读写 | 登录、会话列表、可见消息、监听、发文本 |
| `ReadLatest` / `ReadContext` / `CaptureMessageMedia` | **仅 GUI 路径**；openclaw 上为 UNIMPLEMENTED / 空 |

```python
from callus.adapter import CallusClient

with CallusClient("127.0.0.1:7701") as c:
    latest = c.read_latest("某群")
```

## 布局

```
openclaw/       # 非 GUI ilink 客户端 + gRPC servicer（本分支主路径）
agent/          # GUI AT-SPI 实现（遗留 / 其它分支）
wejam/          # 线兼容客户端 + stub
callus/         # CaptureDriver（GUI）
proto/wejam/v1/ # 契约
docs/openclaw.md
scripts/run-openclaw.sh
docker/         # GUI 镜像
```

`data/openclaw/` 存 token（gitignore）；勿提交。
