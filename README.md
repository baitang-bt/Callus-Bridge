# Callus-Bridge

微信 **数据抓取** 桥（无 AI 大脑）。仓库：[baitang-bt/Callus-Bridge](https://github.com/baitang-bt/Callus-Bridge)。

与当前 WeJamBot 使用的 bridge **线兼容**：`package wejam.v1` / `service WeJam` / 既有 RPC 与字段号不变。宿主把 `WEJAM_TARGET` 指到 Callus 端口即可换桥。Callus 只 **追加** `ReadContext` / `ReadLatest` / `CaptureMessageMedia` 与可选 `attachments`。

本仓从 WeJam 的 bridge 侧 **拷贝** 后演进，不修改 WeJamBot 仓内的 `agent/`。

## 能力

| 能力 | 说明 |
|------|------|
| 既有读写 | 登录、会话列表、可见消息、监听、发文本（同 WeJam） |
| `ReadLatest` | 最新一条 + 发送者昵称，不等滚动 |
| `ReadContext(chat, limit)` | 向上滚动凑上下文；`limit` 由调用方传入 |
| `CaptureMessageMedia` | 气泡裁图；动画抽帧，不变则静帧 `sampled=false` |

## 快速开始

```bash
make build
make up          # 127.0.0.1:7701
WEJAM_TARGET=127.0.0.1:7701 python -m wejam.cli status
```

Python：

```python
from callus.adapter import CallusClient

with CallusClient("127.0.0.1:7701") as c:
    latest = c.read_latest("某群")
    ctx = c.read_context("某群", limit=30)
```

## 布局

```
agent/          # 容器内 AT-SPI 实现（拷贝自 WeJam bridge 后扩展）
wejam/          # 线兼容客户端 + 生成 stub
callus/         # CaptureDriver 协议与适配器
proto/wejam/v1/ # 契约（既有 + 增量）
docker/         # 独立镜像与 callus-session 卷
docs/probe.md   # 探测记录
```

媒体文件写在卷内 `CALLUS_MEDIA_DIR`（默认 `/data/media`），不进 git。
