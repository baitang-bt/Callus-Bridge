# Agent Context — Callus-Bridge

> 与 WeJamBot 大脑分离的数据抓取桥。线兼容 `wejam.v1`。

## 当前焦点

- **OpenClaw 非 GUI 桥**（`feat/openclaw-non-gui`，`:7702`）— 接手说明见 [`handoff-openclaw.md`](./handoff-openclaw.md)
- GUI `agent/`（`:7701`）保留为遗留；宿主默认走 openclaw
- 独立仓库演进；不把 openclaw 默认实现搬进 WeJamBot `bot/`

## 架构与决策

| ID | 日期 | 决策 |
|----|------|------|
| d1 | 2026-10-23 | 从 WeJam bridge 拷贝后改；保留 `package wejam.v1` / `service WeJam` |
| d2 | 2026-10-23 | `limit` 由宿主传入；默认端口 7701 |
| d3 | 2026-10-23 | 动画不变则静帧 `sampled=false` |

## 关键路径

| 用途 | 路径 |
|------|------|
| 契约 | `proto/wejam/v1/wejam.proto` |
| OpenClaw 桥 | `openclaw/`；`docs/openclaw.md` |
| OpenClaw 接手 | `docs/agent/handoff-openclaw.md` |
| GUI 遗留 | `agent/`（含 `capture.py`），端口 7701 |
| 宿主客户端 | WeJamBot 侧 `wejam` / CallusClient；本仓 `wejam/client.py`、`callus/adapter.py` |
