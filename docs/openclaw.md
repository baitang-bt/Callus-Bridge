# OpenClaw 非 GUI 桥（字段映射）

本分支用腾讯个人微信 **ilink / openclaw** HTTP 接口收发，经 `wejam.v1` gRPC 暴露给 WeJamBot。  
默认端口 **7702**。不启动 Xvfb / Linux 微信。

参考公开接口形态（不复制第三方源码）：[AstrBot 个人微信接入](https://docs.astrbot.app/platform/weixin_oc.html)。

## 端点

| 用途 | 方法 | 路径 |
|------|------|------|
| 申请登录二维码 | GET | `ilink/bot/get_bot_qrcode?bot_type=3` |
| 轮询扫码状态 | GET | `ilink/bot/get_qrcode_status?qrcode=…` |
| 长轮询入站 | POST | `ilink/bot/getupdates` |
| 发送 | POST | `ilink/bot/sendmessage` |

Base URL 默认 `https://ilinkai.weixin.qq.com`。  
`channel_version` 固定为 `callus-bridge`。

## 登录态字段 → wejam

| openclaw / 本地状态 | wejam |
|---------------------|--------|
| 无 token | `LOGIN_PHASE_QR_READY`（有有效 QR）或 `STARTING` |
| 扫码确认中 | `LOGIN_PHASE_WAIT_PHONE` |
| `bot_token` + `ilink_bot_id` 已落盘 | `LOGIN_PHASE_LOGGED_IN` |
| QR 内容 `qrcode_img_content` | `LoginQRCode.payload`（客户端据此渲染） |
| QR 句柄 `qrcode` | 仅服务端轮询用，不单独暴露 |

## 入站消息 → `Message` / 宿主 `SeenMessage`

| openclaw `msgs[]` | wejam `Message` | 宿主 `SeenMessage` |
|-------------------|-----------------|-------------------|
| `from_user_id` | `chat`（默认；见 aliases） | `chat` |
| `from_user_id`（单聊） | `sender` 空或同 chat | `sender` |
| `item_list[].text_item.text`（type=1） | `text` | `text` |
| 非文本 item | `text` 占位如 `[图片]`，`content_type` 对应 | 同左 |
| `message_id` / `msg_id` | `id` | `message_id` |
| `create_time` / `create_time_ms` | `time_text`（可读） | — |
| 本 bot 发出 | `from_self=true` | `from_self` |
| （完整正文） | `preview_only=false` | `preview=false` |
| `context_token` | 不进 Message；写入该 chat 的发送凭证 | — |

## 会话列表与白名单

openclaw 不以「微信备注名」为稳定主键，默认 **`chat = from_user_id`**。

可选别名文件 `data/openclaw/aliases.json`：

```json
{
  "by_id": {
    "ilink_user_xxx": "白糖"
  }
}
```

- `ListChats.name` / Watch / Send：对外优先用别名（有则显示名）。
- 宿主 `allow_chats.txt` 应写**别名后的名字**（如 `白糖`），或直接写 `from_user_id`。
- `SendText(chat=…)`：先按别名反查 id，找不到则把 `chat` 当 id。

## 发送约束

- 必须已登录（有 token）。
- 目标会话必须已有 `context_token`（通常来自对方先发一条）。否则 `SendResult.ok=false`，detail 说明需先有入站。

## 本桥不做的 RPC

| RPC | 行为 |
|-----|------|
| `ReadContext` / `ReadLatest` / `CaptureMessageMedia` | `UNIMPLEMENTED` 或空结果 + 明确 detail |
| `DumpA11yTree` / `InvokeNode` / `GetBadges` / `InvokeMessage` | `UNIMPLEMENTED` |
| GUI `Logout` | 清除本地 token 并回到待扫码（不点微信设置） |

## 状态落盘

目录：`data/openclaw/`（gitignore）

- `state.json`：token、account_id、base_url、sync_buf、context_tokens、recent chats 预览
- `aliases.json`：可选显示名映射
