# 接手：Callus-Bridge · OpenClaw 非 GUI 桥（续作 / 验收）

### 背景与风险规避目标

WeJamBot 原先用 **Linux 微信 + AT-SPI/合成点击（GUI）** 收发，易触发设备锁、「协助诈骗」等风控。已拍板：

- **消息 SoT** 迁到 [baitang-bt/Callus-Bridge](https://github.com/baitang-bt/Callus-Bridge) 的 **非 GUI** 通道。
- 用腾讯个人微信 **openclaw / ilink**（扫码 + 长轮询），思路对齐 AstrBot `weixin_oc`，**只借鉴接口形态，禁止复制 AstrBot 源码**。
- **风险规避目标（做得到 / 做不到）**
  - **要降低的**：不再在容器里「演戏」点微信窗口（无障碍点击、Xvfb 挂机），减少设备锁/异常客户端画像。
  - **做不到的**：不是零风控；仍是个人号 bot 能力，不能绕过平台判定，禁止做绕检测/刷设备指纹一类事。
  - **使用原则**：低频、可停、白名单克制；账号未解限不做活体压测。

本地仓：`/Users/max/Documents/Agent/projects/Callus-Bridge`  
分支（已推送）：`feat/openclaw-non-gui`  
Plan 参考：`~/.cursor/plans/openclaw_eyes_adapter_e638184c.plan.md`（勿改 Plan 文件；以仓库现状为准）

宿主 WeJamBot：大脑只认 `WeChatEyes`；`WEJAM_TARGET` 指桥即可。文档已倾向 `:7702`。

### 技术方案

```
WeJamBot brain → WeJamHands / CallusClient (wejam.v1 gRPC)
                    → Callus-Bridge openclaw (:7702)
                    → https://ilinkai.weixin.qq.com  (ilink/bot/*)
```

| 能力 | 实现要点 |
|------|----------|
| 登录 | `GET ilink/bot/get_bot_qrcode?bot_type=3`；`GET ilink/bot/get_qrcode_status` → 存 `bot_token` / `ilink_bot_id` |
| 收 | `POST ilink/bot/getupdates`（Bearer + `get_updates_buf`）→ `WatchMessages` |
| 发 | `POST ilink/bot/sendmessage`；需会话 `context_token`（通常来自入站）；纯文本 `item_list` type=1 |
| 头 | `AuthorizationType: ilink_bot_token`；`channel_version=callus-bridge`（勿写 astrbot） |
| 线协议 | 保持 `wejam.v1`；GUI 专属 RPC（ReadContext/Capture/a11y 等）→ **UNIMPLEMENTED/明确失败**，禁止静默假成功 |
| 会话名 | 默认 `chat=from_user_id`；可选 `data/openclaw/aliases.json` 的 `by_id` 映射到白名单显示名 |
| 端口 | **7702**（避开 GUI Callus `7701`、WeJam `7700`） |
| 运行时 | **不起** Xvfb / Linux 微信；`make openclaw` / `python -m openclaw` |

文档：`docs/openclaw.md`、`README.md`、`docker/README.openclaw.md`。

### 当前进度（上一对话已完成）

- 已实现并 push：`openclaw/`（client / store / mapping / runtime / server / `__main__`）、单测、Makefile、字段文档。
- 实测：`make openclaw` 后 `wejam.cli status` → `ready=True`，`login_phase=QR_READY`，ilink `get_bot_qrcode` HTTP 200。
- WeJamBot 侧已薄改：`.env.example` / README / `acceptable-use` / `docs/agent/context.md` d7 / 控制台「微信画面」标明仅遗留 GUI。
- **未完成 / 请你接力**：解限后扫码活体（Watch→Send）、aliases 实战、缺 context_token 体验是否够清楚、PR 到 Callus `main`（若需要）、代码审查与回归测试加固。

### 实现 / 验收目标

1. 分支可独立跑通：登录 QR → 登录成功 → 白名单会话收一条 → 回一条（需先有入站拿 `context_token`）。
2. WeJamBot：`WEJAM_TARGET=127.0.0.1:7702` 起 runner，控制台登录走既有 QR/Status RPC。
3. GUI 路径保持遗留、不删；默认文档与操作不诱导走 GUI 收发。
4. 密钥/token 只在 `data/openclaw/`（gitignore），不进 git。
5. 单测保持绿；必要时补 send/getupdates 边界用例。

### 必做：代码检查与功能测试

开工前：`cd …/Callus-Bridge && git fetch && git checkout feat/openclaw-non-gui && git pull`。

完成后请自行：

1. **代码检查**：模块边界、注释、脱敏、无 GUI 下危险 RPC 行为、与 `docs/openclaw.md` 一致；对照 maintainable-code / api-env-redaction。
2. **单测**：`pytest tests/test_openclaw_*.py -q`（及仓内其它相关测试）。
3. **功能测试**（账号已解限后）：
   - `make openclaw` → `make openclaw-status` / GetLoginQRCode → 手机扫码
   - WatchMessages 收到入站 → SendText 成功
   - WeJamBot `WEJAM_TARGET=127.0.0.1:7702` 白名单来回一条
4. **汇报**：改动路径、如何启动、测试结果、剩余风险/未完成项。未解限则注明「仅离线/QR_READY 验证，活体未做」。

### 明确不要做

- 不把 openclaw 默认实现搬进 WeJamBot `bot/`（避免双 SoT）
- 不接企微/客服（除非用户另开任务）
- 不复制 AstrBot 代码、不实现绕过风控
- 未要求不要 force-push；推送个人仓用既有 `PERSONAL_GH_TOKEN` 流程

### 建议开场一句

「继续 Callus-Bridge `feat/openclaw-non-gui`：核对已 push 的 openclaw 桥，做代码检查与（解限后）活体收发测试，补齐缺口后开/更新 PR。」
