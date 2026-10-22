# 只读探测记录（2026-10-23）

对正在跑的 `wejam-session` 做探测（Callus 尚未单独起容器；能力与拷贝的 Linux AT-SPI 路径相同）。

## 环境

- 容器：`wejam-session` 在线
- 界面：登录页（「扫码登录 / 二维码 / 仅传输文件」）
- `list_chats()` → 0；可见无障碍节点约 21 个

## 结论

| 项 | 结果 |
|----|------|
| 滚动读上下文 | 已登录会话里有 `list`「消息」与 `Page_Up` 注入；本轮未登录，未做活测。Callus 按该路径实现，失败如实报错。 |
| 气泡矩形 | 代码路径 `message_actions.bubble_rect` 已在源 bridge 验证过；登录后可用。 |
| 动态表情 | 未登录无法测像素变化。策略：两帧相同 → 静帧并标记 `sampled=false`。 |

## 接口约束

Callus **沿用现有 bridge 的 gRPC 契约**（`package wejam.v1` / `service WeJam` / 现有 RPC 与字段号不变）。宿主只需改 `WEJAM_TARGET` 即可切换。滚动与表情为**增量** RPC，旧客户端忽略即可。
