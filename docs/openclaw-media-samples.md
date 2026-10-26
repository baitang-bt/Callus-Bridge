# OpenClaw 入站媒体样本说明

> 活体样本用 `scripts/probe_openclaw_media.py` 抓取（脱敏后写入 `data/openclaw/probe/`，gitignore）。  
> 本文记录**协议已知字段**与**实现策略**；未登录时无合成样例验证代码路径。

## 协议已知 `item_list.type`

| type | 结构 | Callus 行为 |
|------|------|-------------|
| 1 | `text_item.text` | 正文 |
| 2 | `image_item` + CDN | 下载 AES-128-ECB 解密 → `attachments`；GIF/WebP 标 `emotion` |
| 3 | `voice_item` | **优先 `voice_item.text` 云端转写**；无转写则 `[语音]` |
| 4 | `file_item` | 普通文件落盘；文件名含「聊天记录/合并转发」→ `content_type=merge` 并尝试解正文 |
| 5 | `video_item` | 占位 `[视频]`（本阶段不下视频） |
| 11/12 | tool call | 忽略 / 占位 |

参考：[Tencent/openclaw-weixin protocol.md](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol.md)（只借鉴字段形态）。

## 合并转发

官方 MessageItem **无独立 merge 类型**。实现采用：

1. `file_item.file_name` 命中「聊天记录 / 合并转发」→ 下载后 UTF-8/XML 抽文本；失败则明确占位文案（请复制或逐条转发）。
2. 纯文本里出现「合并转发」字样 → `content_type=merge`。
3. 若活体 dump 显示其它形状，用探针 JSON 更新本节后再加解析器。

## 表情包

无独立 emotion type。策略：图片管道路径；解密后若为 `.gif` / `.webp` 则 `content_type=emotion` 且 `attachments.kind=emotion`。宿主有 `image_paths` 时**不再**调 GUI `CaptureMessageMedia`。

## 活体探针状态

| 类型 | 状态 |
|------|------|
| 图片 | 代码路径已实现；待发图后探针确认 CDN 字段 |
| 语音转写 | 映射已实现；待发语音确认 `voice_item.text` 是否总是带上 |
| 合并转发 | 文件名启发式 + 降级文案；待活体确认真实载荷 |
| 表情 | 按 GIF/WebP 启发式；待活体确认是否走 image_item |

运行：

```bash
make openclaw          # 另开终端
# 手机向 bot 发图/语音/合并/表情
.venv/bin/python scripts/probe_openclaw_media.py --wait 120
```
