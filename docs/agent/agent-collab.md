# Agent Collab — Callus-Bridge


> 多 Agent / 多对话共享的**项目协作记忆**。由 `context.md` 迁移于 2026-11-11 19:57 +0800。
> 最后更新：2026-11-11 19:57 +0800

## 读哪些

| 场景 | 读 |
|------|-----|
| 接手 / 新对话 / 子 Agent 默认 | **当前焦点** + **活跃泳道** + **阻塞** + **Handoff** |
| 要改架构或核对旧结论 | 再读 **架构与决策**（或 `docs/agent/decisions.md`） |
| 禁止 | 整份灌进上下文；勿读整个 `conversations/` |

## 当前焦点

- **GUI `:7701` 为主路径**（可进个人微信群）；openclaw `:7702` 为私聊旁路
- 独立仓库演进；不改 WeJamBot 的 `agent/`
- 增量 RPC：`ReadLatest` / `ReadContext` / `CaptureMessageMedia`

## 活跃泳道

| 对话 | lane | 负责范围 | 状态 | 更新 |
|------|------|----------|------|------|


## 阻塞 / 未决

- **阻塞**：无


## Handoff

- （待填）


## 架构与决策

| ID | 日期 | 决策 |
|----|------|------|
| d1 | 2026-10-23 | 从 WeJam bridge 拷贝后改；保留 `package wejam.v1` / `service WeJam` |
| d2 | 2026-10-23 | `limit` 由宿主传入；默认端口 7701 |
| d3 | 2026-10-23 | 动画不变则静帧 `sampled=false` |
| d4 | 2026-10-26 | 群聊 SoT = GUI Callus；openclaw 不能进个人群，仅私聊可选 |
| d5 | 2026-10-26 | GUI 等价物：日志 `redact`、capture `.part`+20MB、可选入站 voice 菜单探测 / 自动裁图；不搬 CDN/ilink |


## 进展

- [ ] 


## 关键路径

| 用途 | 路径 |
|------|------|
| 契约 | `proto/wejam/v1/wejam.proto` |
| 容器内实现 | `agent/`（含 `capture.py`、`enrich.py`、`redact.py`） |
| openclaw 旁路 | `openclaw/`（`:7702`，私聊） |
| 宿主客户端 | `wejam/client.py`、`callus/adapter.py` |

## 专题文档

| 文档 | 用途 |
|------|------|
