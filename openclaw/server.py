"""wejam.v1 gRPC servicer backed by OpenClawRuntime (no GUI)."""

from __future__ import annotations

import logging
import time
from concurrent import futures

import grpc

from openclaw import DEFAULT_PORT
from openclaw import runtime as rt
from wejam.v1 import wejam_pb2, wejam_pb2_grpc

_log = logging.getLogger(__name__)

PHASE_TO_PROTO = {
    rt.PHASE_STARTING: wejam_pb2.LOGIN_PHASE_STARTING,
    rt.PHASE_QR_READY: wejam_pb2.LOGIN_PHASE_QR_READY,
    rt.PHASE_WAIT_PHONE: wejam_pb2.LOGIN_PHASE_WAIT_PHONE,
    rt.PHASE_LOGGED_IN: wejam_pb2.LOGIN_PHASE_LOGGED_IN,
    rt.PHASE_UNKNOWN: wejam_pb2.LOGIN_PHASE_UNKNOWN,
}


class OpenClawServicer(wejam_pb2_grpc.WeJamServicer):
    """Wire-compatible WeJam service using openclaw HTTP only."""

    def __init__(self, machine: rt.OpenClawRuntime) -> None:
        self.machine = machine

    def GetStatus(self, request, context):
        """Report readiness and login phase without probing a WeChat process."""
        snap = self.machine.snapshot()
        return wejam_pb2.Status(
            ready=snap["phase"] != rt.PHASE_STARTING,
            wechat_version="openclaw",
            login_phase=PHASE_TO_PROTO.get(
                snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED
            ),
            uptime_ms=self.machine.uptime_ms(),
        )

    def _state_msg(self, snap=None):
        """Build LoginState from a runtime snapshot."""
        snap = snap or self.machine.snapshot()
        return wejam_pb2.LoginState(
            phase=PHASE_TO_PROTO.get(snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED),
            detail=snap["detail"],
            since_unix_ms=snap["since_unix_ms"],
            markers=snap["markers"],
        )

    def GetLoginState(self, request, context):
        """Unary login snapshot."""
        return self._state_msg()

    def WatchLogin(self, request, context):
        """Stream login phase changes."""
        q = self.machine.subscribe_login()
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
            self.machine.unsubscribe_login(q)

    def GetLoginQRCode(self, request, context):
        """Return current QR payload (qrcode_img_content) when in QR_READY."""
        qr = self.machine.qr()
        if not qr["payload"]:
            context.abort(
                grpc.StatusCode.NOT_FOUND,
                "当前没有可用的二维码（可能已登录或不在二维码状态）",
            )
        return wejam_pb2.LoginQRCode(
            payload=qr["payload"],
            revision=qr["revision"] or "",
            fetched_unix_ms=qr["fetched_unix_ms"],
        )

    def SubmitLogin(self, request, context):
        """No one-click path on openclaw; return current state."""
        return self._state_msg()

    def Logout(self, request, context):
        """Clear local token and return to QR (no GUI settings click)."""
        snap = self.machine.snapshot()
        if snap["phase"] != rt.PHASE_LOGGED_IN:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "当前未登录，无法退出")
        self.machine.logout_local("local logout")
        time.sleep(0.2)
        return self._state_msg()

    def GetAccountSummary(self, request, context):
        """Minimal account summary without a11y."""
        snap = self.machine.snapshot()
        logged_in = snap["phase"] == rt.PHASE_LOGGED_IN
        chats = self.machine.list_chats() if logged_in else []
        unread_chats = sum(1 for c in chats if c.get("unread_count"))
        unread_msgs = sum(int(c.get("unread_count") or 0) for c in chats)
        return wejam_pb2.AccountSummary(
            logged_in=logged_in,
            wechat_version="openclaw",
            login_phase=PHASE_TO_PROTO.get(
                snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED
            ),
            login_detail=snap["detail"],
            login_since_unix_ms=snap["since_unix_ms"],
            uptime_ms=self.machine.uptime_ms(),
            chat_count=len(chats),
            unread_chats=unread_chats,
            unread_messages=unread_msgs,
            account_hint="",
        )

    def ListChats(self, request, context):
        """Chats inferred from inbound openclaw traffic."""
        return wejam_pb2.ListChatsResponse(
            chats=[wejam_pb2.Chat(**c) for c in self.machine.list_chats()]
        )

    def ListMessages(self, request, context):
        """Recent cached messages for one chat (no scroll history)."""
        name, msgs = self.machine.list_messages(request.chat, request.limit)
        return wejam_pb2.ListMessagesResponse(
            chat=name,
            chat_type="single",
            member_count=0,
            messages=[self._message_proto(m) for m in msgs],
        )

    def _message_proto(self, m: dict) -> wejam_pb2.Message:
        """Map internal dict onto wire Message including local media attachments."""
        media = []
        for item in m.get("attachments") or ():
            if not isinstance(item, dict):
                continue
            media.append(
                wejam_pb2.MediaAttachment(
                    kind=str(item.get("kind") or ""),
                    path=str(item.get("path") or ""),
                    sha256=str(item.get("sha256") or ""),
                    sampled=bool(item.get("sampled")),
                    frame_index=int(item.get("frame_index") or 0),
                )
            )
        return wejam_pb2.Message(
            id=m.get("id", ""),
            chat=m.get("chat", ""),
            sender=m.get("sender", ""),
            text=m.get("text", ""),
            time_text=m.get("time_text", ""),
            kind=getattr(wejam_pb2, f"MESSAGE_KIND_{m.get('kind', 'TEXT')}", wejam_pb2.MESSAGE_KIND_TEXT),
            index=int(m.get("index") or 0),
            preview_only=bool(m.get("preview_only")),
            from_self=bool(m.get("from_self")),
            content_type=m.get("content_type") or "text",
            stable_id=m.get("stable_id") or "",
            attachments=media,
        )

    def WatchMessages(self, request, context):
        """Stream new inbound messages; optional chat filter."""
        target = (request.chat or "").strip()
        while context.is_active():
            msg = self.machine.pop_inbox(timeout=1.0)
            if msg is None:
                continue
            if target and msg.get("chat") != target and msg.get("user_id") != target:
                # Also match alias vs id if client filtered by either form.
                if target not in {msg.get("chat"), msg.get("user_id"), msg.get("stable_id")}:
                    continue
            yield wejam_pb2.MessageEvent(
                chat=msg.get("chat", ""),
                at_unix_ms=int(time.time() * 1000),
                added=[self._message_proto(msg)],
                unread=0,
            )

    def SendText(self, request, context):
        """Send via openclaw; fails without context_token."""
        ok, detail = self.machine.send_text(request.chat, request.text)
        return wejam_pb2.SendResult(ok=ok, detail=detail)

    def InvokeMessage(self, request, context):
        """GUI-only action; not available on openclaw."""
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "openclaw bridge: InvokeMessage unsupported")

    def ReadContext(self, request, context):
        """No scroll history on openclaw; refuse rather than fake."""
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "openclaw bridge: ReadContext unsupported")

    def ReadLatest(self, request, context):
        """Best-effort: newest cached message for chat, or empty."""
        name, msgs = self.machine.list_messages(request.chat, 1)
        latest = msgs[-1] if msgs else None
        return wejam_pb2.ReadLatestResponse(
            chat=name,
            message=self._message_proto(latest) if latest else wejam_pb2.Message(),
            chat_type="single",
            member_count=0,
        )

    def CaptureMessageMedia(self, request, context):
        """No bubble crop without GUI."""
        return wejam_pb2.CaptureMessageMediaResponse(
            ok=False,
            detail="openclaw bridge: CaptureMessageMedia unsupported",
            attachments=[],
        )

    def GetBadges(self, request, context):
        """No nav-badge pixels without GUI."""
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "openclaw bridge: GetBadges unsupported")

    def DumpA11yTree(self, request, context):
        """No AT-SPI tree on openclaw."""
        context.abort(grpc.StatusCode.UNIMPLEMENTED, "openclaw bridge: DumpA11yTree unsupported")

    def InvokeNode(self, request, context):
        """No UI clicks on openclaw."""
        return wejam_pb2.InvokeNodeResponse(
            ok=False,
            detail="openclaw bridge: InvokeNode unsupported",
        )


def serve(port: int = DEFAULT_PORT, machine: rt.OpenClawRuntime | None = None) -> None:
    """Start gRPC server on port; blocks until KeyboardInterrupt."""
    runtime = machine or rt.OpenClawRuntime()
    runtime.start()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    wejam_pb2_grpc.add_WeJamServicer_to_server(OpenClawServicer(runtime), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"[openclaw] gRPC listening on :{port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        runtime.stop()
        server.stop(0)
