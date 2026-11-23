"""WeJamBot agent：容器内的 gRPC 服务。

它持有登录状态机（见 login.py），对外只暴露契约里的能力与状态。
客户端不需要知道容器里发生了什么。
"""
import hashlib
import os
import subprocess
import sys
import time
from concurrent import futures

import grpc

_HERE = os.path.dirname(os.path.abspath(__file__))
# 契约代码是 wejam 包的子包（wejam/v1），镜像里放在 /opt/wejam/wejam/v1。
# 把 /opt/wejam 放进 sys.path 即可 `from wejam.v1 import ...`。
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))

from wejam.v1 import wejam_pb2, wejam_pb2_grpc  # noqa: E402

from . import accessibility, badges, capture, chat, enrich, geometry, login, message_actions, selflog, session_account, wechat_info  # noqa: E402
from . import input as inputmod  # noqa: E402


def _dict_to_message(m: dict, *, preview_only: bool = False) -> wejam_pb2.Message:
    """Build a wire Message from a chat.list_messages / capture row dict."""
    attachments = []
    for row in m.get("attachments") or []:
        if not isinstance(row, dict):
            continue
        attachments.append(
            wejam_pb2.MediaAttachment(
                kind=str(row.get("kind") or ""),
                path=str(row.get("path") or ""),
                sha256=str(row.get("sha256") or ""),
                sampled=bool(row.get("sampled")),
                frame_index=int(row.get("frame_index") or 0),
            )
        )
    return wejam_pb2.Message(
        id=m.get("id", ""),
        chat=m.get("chat", ""),
        sender=m.get("sender", ""),
        text=m.get("text", ""),
        time_text=m.get("time_text", ""),
        kind=getattr(wejam_pb2, f"MESSAGE_KIND_{m.get('kind', 'TEXT')}"),
        index=int(m.get("index", 0) or 0),
        preview_only=preview_only,
        from_self=selflog.is_own(m.get("chat", ""), m.get("text", "")),
        content_type=m.get("content_type", "text"),
        attachments=attachments,
        quote_text=m.get("quote_text", "") or "",
        quote_sender=m.get("quote_sender", "") or "",
    )

PORT = int(os.environ.get("WEJAM_PORT", "7700"))
PHASE_TO_PROTO = {
    login.PHASE_UNSPECIFIED: wejam_pb2.LOGIN_PHASE_UNSPECIFIED,
    login.PHASE_STARTING: wejam_pb2.LOGIN_PHASE_STARTING,
    login.PHASE_QR_READY: wejam_pb2.LOGIN_PHASE_QR_READY,
    login.PHASE_ONE_CLICK_READY: wejam_pb2.LOGIN_PHASE_ONE_CLICK_READY,
    login.PHASE_WAIT_PHONE: wejam_pb2.LOGIN_PHASE_WAIT_PHONE,
    login.PHASE_LOGGED_IN: wejam_pb2.LOGIN_PHASE_LOGGED_IN,
    login.PHASE_UNKNOWN: wejam_pb2.LOGIN_PHASE_UNKNOWN,
}


class WeJamServicer(wejam_pb2_grpc.WeJamServicer):
    def __init__(self, machine: login.LoginMachine):
        self.machine = machine

    # ---------- 状态 ----------
    def GetStatus(self, request, context):
        snap = self.machine.snapshot()
        version, source = wechat_info.detect()
        return wejam_pb2.Status(
            ready=snap["phase"] not in (login.PHASE_STARTING,),
            wechat_version=version,
            login_phase=PHASE_TO_PROTO.get(snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED),
            uptime_ms=self.machine.uptime_ms(),
        )

    # ---------- 登录 ----------
    def _state_msg(self, snap=None):
        snap = snap or self.machine.snapshot()
        return wejam_pb2.LoginState(
            phase=PHASE_TO_PROTO.get(snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED),
            detail=snap["detail"],
            since_unix_ms=snap["since_unix_ms"],
            markers=snap["markers"],
        )

    def GetLoginState(self, request, context):
        return self._state_msg()

    def WatchLogin(self, request, context):
        q = self.machine.subscribe()
        try:
            yield self._state_msg()
            while context.is_active():
                try:
                    snap = q.popleft()
                except IndexError:
                    time.sleep(0.3)
                    continue
                yield self._state_msg(snap)
        finally:
            self.machine.unsubscribe(q)

    def GetLoginQRCode(self, request, context):
        """Return the login QR. Refresh metadata decodes the screen first."""
        if _wants_fresh_qr(context):
            qr = self.machine.read_screen_qr()
            if qr is None:
                context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    "屏幕上没有解出二维码（微信可能不在扫码界面）",
                )
        else:
            qr = self.machine.qr()
        if not qr["payload"]:
            context.abort(grpc.StatusCode.NOT_FOUND,
                          "当前没有可用的二维码（可能不在二维码状态）")
        return wejam_pb2.LoginQRCode(
            payload=qr["payload"],
            revision=qr["revision"] or "",
            fetched_unix_ms=qr["fetched_unix_ms"],
        )

    def SubmitLogin(self, request, context):
        ok, detail = self.machine.submit_login()
        if not ok:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, detail)
        return self._state_msg()

    def Logout(self, request, context):
        snap = self.machine.snapshot()
        if snap["phase"] != login.PHASE_LOGGED_IN:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "当前未登录，无法退出")
        ok, detail = session_account.logout()
        if not ok:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, detail)
        # Give the login poller a moment to observe the post-logout UI.
        time.sleep(1.0)
        return self._state_msg()

    def GetAccountSummary(self, request, context):
        snap = self.machine.snapshot()
        logged_in = snap["phase"] == login.PHASE_LOGGED_IN
        raw = session_account.build_summary(
            phase=PHASE_TO_PROTO.get(snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED),
            detail=snap["detail"],
            since_ms=snap["since_unix_ms"],
            uptime_ms=self.machine.uptime_ms(),
            logged_in=logged_in,
        )
        return wejam_pb2.AccountSummary(**raw)

    # ---------- 会话与消息 ----------
    def ListChats(self, request, context):
        return wejam_pb2.ListChatsResponse(chats=[
            wejam_pb2.Chat(**c) for c in chat.list_chats()
        ])

    def ListMessages(self, request, context):
        try:
            name, msgs = chat.list_messages(request.chat, request.limit)
        except RuntimeError as e:
            # 例如「打开会话失败」——必须如实上报，不能返回别的会话的消息
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        info = chat.chat_header_info(name)
        return wejam_pb2.ListMessagesResponse(
            chat=name,
            chat_type=info["chat_type"],
            member_count=info["member_count"],
            messages=[_dict_to_message(m) for m in msgs],
        )

    def WatchMessages(self, request, context):
        """增量推送。

        两种模式：
          * 指定 chat  -> 单会话精细监听，能拿完整正文；
                          代价是服务端要保持该会话打开（会清掉它的未读）。
          * 不指定     -> **全局监听**：轮询会话列表的预览变化，覆盖所有会话，
                          完全不打开任何会话（不动界面、不清未读）；
                          代价是只能给预览文本（可能被截断），preview_only=true。
        """
        if not request.chat:
            yield from self._watch_global(context)
        else:
            yield from self._watch_single(request.chat, context)

    # ---------- 全局监听：只读会话列表，不碰界面 ----------
    @staticmethod
    def _is_new_message(prev, cur):
        """判断会话预览的变化是否意味着「来了新消息」。

        注意区分「用户读了（未读减少）」与「来了新的」——前者不该报。
        """
        if cur["last_message"] != prev["last_message"]:
            return True
        if cur["last_time"] != prev["last_time"]:
            return True
        return cur["unread_count"] > prev["unread_count"]

    @staticmethod
    def _preview_to_message(c):
        """把会话列表的一行预览变成一条 Message（preview_only）。"""
        from .sender_name import split_preview_sender

        # 群聊预览形如 "崔欣宇: 正文" / "昵称：正文"；拆出发送者（拒绝 [链接] 等）
        sender, text = split_preview_sender(c["last_message"])
        mid = hashlib.sha1(
            f"{c['name']}|{c['last_message']}|{c['last_time']}|{c['unread_count']}".encode()
        ).hexdigest()[:16]
        from .quote_parse import parse_quote_message

        quote_text = ""
        quote_sender = ""
        content_type = "text"
        parts = parse_quote_message(c["last_message"]) or parse_quote_message(text)
        if parts is not None:
            content_type = "quote"
            quote_text = parts.quote_text
            quote_sender = parts.quote_sender
            if parts.body.strip():
                text = parts.body.strip()
        return wejam_pb2.Message(
            id=mid,
            chat=c["name"],
            sender=sender,
            text=text,
            time_text=c["last_time"],
            kind=wejam_pb2.MESSAGE_KIND_TEXT,
            preview_only=True,
            from_self=selflog.is_own(c["name"], c["last_message"]),
            content_type=content_type,
            quote_text=quote_text,
            quote_sender=quote_sender,
        )

    def _watch_global(self, context):
        prev = {}
        while context.is_active():
            try:
                chats = chat.list_chats()
            except Exception:
                time.sleep(1.5)
                continue

            cur = {c["name"]: c for c in chats}
            if prev:
                changed = [c for name, c in cur.items()
                           if name in prev and self._is_new_message(prev[name], c)]
                # 按会话逐个推送：带上该会话未读数，客户端据此判断漏没漏
                for c in changed:
                    yield wejam_pb2.MessageEvent(
                        chat=c["name"],
                        at_unix_ms=int(time.time() * 1000),
                        added=[self._preview_to_message(c)],
                        unread=c["unread_count"],
                    )
            # 首轮只建基线；新出现的会话也从下一轮起纳入基线
            prev = cur
            time.sleep(1.0)

    def _watch_single(self, target, context):
        """单会话精细监听。

        关键点：会话切换（或首次变得可见）时必须重建基线，否则一打开会话
        就会把整段历史当成新消息推给订阅者 —— 实测中确实踩到过。
        """
        seen = set()
        last_chat = None
        settle_until = 0.0
        while context.is_active():
            try:
                name, msgs = chat.list_messages(target, 0)
            except Exception:
                time.sleep(1.0)
                continue

            texts = [(m["chat"], m["id"]) for m in msgs if m["kind"] == "TEXT"]
            if name != last_chat:
                # 首次可见 / 换了会话：进入稳定期，只建基线，不推送历史
                last_chat = name
                seen = set(texts)
                settle_until = time.time() + 3.0
                time.sleep(1.5)
                continue

            if time.time() < settle_until:
                # 刚打开会话时列表仍在渲染，晚出现的消息不能算「新」。
                # 持续把当前可见的并入基线，等渲染稳定。
                seen |= set(texts)
                time.sleep(1.5)
                continue

            added = [m for m in msgs
                     if m["kind"] == "TEXT" and (m["chat"], m["id"]) not in seen]
            if added:
                seen.update((m["chat"], m["id"]) for m in added)
                yield wejam_pb2.MessageEvent(
                    chat=target,
                    at_unix_ms=int(time.time() * 1000),
                    added=[_dict_to_message(m) for m in added],
                )
            time.sleep(1.5)

    def SendText(self, request, context):
        ok, detail = chat.send_text(request.chat, request.text)
        return wejam_pb2.SendResult(ok=ok, detail=detail)

    def InvokeMessage(self, request, context):
        ok, detail, text = message_actions.invoke(request.chat, request.index, request.action)
        return wejam_pb2.InvokeMessageResult(ok=ok, detail=detail, text=text)

    def ReadLatest(self, request, context):
        """Newest bubble in the opened chat (fills sender / quote / voice STT)."""
        try:
            name, latest, info = capture.read_latest(request.chat)
        except RuntimeError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        if latest is None:
            return wejam_pb2.ReadLatestResponse(
                chat=name,
                chat_type=info.get("chat_type", ""),
                member_count=int(info.get("member_count") or 0),
            )
        # Voice STT / image crop on ReadLatest only (not Watch) to avoid UI spam.
        ctype = (latest.get("content_type") or "").strip().lower()
        if ctype == "voice":
            latest = enrich.enrich_voice_transcript(latest)
        elif ctype in {"image", "emotion"}:
            latest = enrich.enrich_media_attachments(latest)
        return wejam_pb2.ReadLatestResponse(
            chat=name,
            message=_dict_to_message(latest),
            chat_type=info.get("chat_type", ""),
            member_count=int(info.get("member_count") or 0),
        )

    def ReadContext(self, request, context):
        """Scroll-collect up to ``limit`` messages for reply history / quote fallback."""
        try:
            name, msgs, info = capture.read_context(request.chat, request.limit)
        except RuntimeError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        return wejam_pb2.ReadContextResponse(
            chat=name,
            messages=[_dict_to_message(m) for m in msgs],
            chat_type=info.get("chat_type", ""),
            member_count=int(info.get("member_count") or 0),
        )

    def CaptureMessageMedia(self, request, context):
        """Crop sticker/image frames for one bubble index."""
        ok, detail, rows = capture.capture_message_media(
            request.chat,
            request.index,
            max_frames=request.max_frames,
            interval_ms=request.interval_ms,
        )
        attachments = [
            wejam_pb2.MediaAttachment(
                kind=row.get("kind", ""),
                path=row.get("path", ""),
                sha256=row.get("sha256", ""),
                sampled=bool(row.get("sampled")),
                frame_index=int(row.get("frame_index") or 0),
            )
            for row in rows
        ]
        return wejam_pb2.CaptureMessageMediaResponse(
            ok=ok, detail=detail, attachments=attachments
        )

    def GetBadges(self, request, context):
        items, unread_chats, unread_msgs = badges.scan_badges()
        return wejam_pb2.GetBadgesResponse(
            badges=[wejam_pb2.NavBadge(label=b["label"], has_badge=b["has_badge"],
                                       red_pixels=b["red_pixels"],
                                       area_pixels=b["area_pixels"]) for b in items],
            unread_chats=unread_chats,
            unread_messages=unread_msgs,
        )

    # ---------- 逃生舱 ----------
    def DumpA11yTree(self, request, context):
        only_visible = request.only_visible if request.HasField("only_visible") else True
        depth = request.max_depth if request.HasField("max_depth") else 45
        nodes = accessibility.walk_all(
            only_visible=only_visible,
            max_depth=depth or 45,
        )
        return wejam_pb2.DumpA11yTreeResponse(nodes=[
            wejam_pb2.A11yNode(depth=n["depth"], role=n["role"], name=n["name"],
                               text=n["text"], states=n["states"])
            for n in nodes
        ])

    def InvokeNode(self, request, context):
        if wechat_info.name_is_dangerous(request.name):
            return wejam_pb2.InvokeNodeResponse(
                ok=False,
                detail=f"拒绝点击危险节点 {request.role}/{request.name}",
            )
        rect = geometry.node_physical_rect(request.role, request.name)
        if rect is None:
            return wejam_pb2.InvokeNodeResponse(ok=False, detail="未找到匹配的可见节点")
        x, y, w, h = rect
        inputmod.click_at(x + w // 2, y + h // 2)
        return wejam_pb2.InvokeNodeResponse(
            ok=True, detail=f"已点击 {request.role}/{request.name} @ ({x + w // 2},{y + h // 2})")


def _wants_fresh_qr(context) -> bool:
    """True when the client asked this pull to re-decode the screen."""
    for key, value in context.invocation_metadata():
        if key == "x-wejam-qr-refresh" and value == "1":
            return True
    return False


def serve():
    machine = login.LoginMachine(
        poll_interval=float(os.environ.get("WEJAM_POLL", "1.0")),
        auto_login=os.environ.get("WEJAM_AUTO_LOGIN", "1") != "0",
    )
    machine.start()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    wejam_pb2_grpc.add_WeJamServicer_to_server(WeJamServicer(machine), server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    print(f"[agent] gRPC listening on :{PORT}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        machine.stop()
        server.stop(0)


if __name__ == "__main__":
    serve()
