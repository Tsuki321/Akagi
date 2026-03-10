import queue
import threading
import time

import mitmproxy.http
import mitmproxy.websocket

from akagi_ng.bridge import (
    AmatsukiBridge,
    BaseBridge,
    MajsoulBridge,
    RiichiCityBridge,
    TenhouBridge,
)
from akagi_ng.mitm_client.logger import logger
from akagi_ng.schema.constants import Platform
from akagi_ng.schema.notifications import NotificationCode
from akagi_ng.schema.types import AkagiEvent, SystemEvent
from akagi_ng.settings import local_settings

# ---------------------------------------------------------------------------
# Optional MajsoulMax mod support
# ---------------------------------------------------------------------------
# The MajsoulMax mod requires proto/liqi_pb2.py which is downloaded at runtime.
# If the file is absent, _MAJSOULMAX_AVAILABLE remains False and the mod is
# silently disabled (a helpful log message is shown).
_MAJSOULMAX_AVAILABLE: bool = False

try:
    from akagi_ng.majsoulmax import update_liqi as _majsoulmax_update_liqi

    _MAJSOULMAX_UPDATE_MODULE_AVAILABLE = True
except ImportError:
    _MAJSOULMAX_UPDATE_MODULE_AVAILABLE = False

# 平台与 URL 识别模式 Mapping
PLATFORM_URL_PATTERNS = {
    Platform.MAJSOUL: ["majsoul", "maj-soul"],
    Platform.TENHOU: ["tenhou.net", "nodocchi"],
    Platform.AMATSUKI: ["amatsukimj", "amatsuki"],
    Platform.RIICHI_CITY: ["mahjong-jp.city", "riichicity"],
}


class BridgeAddon:
    def __init__(self, shared_queue: queue.Queue[AkagiEvent]):
        self.active_majsoul_flow: mitmproxy.http.HTTPFlow | None = None
        # 共享的消息队列（事件驱动模式）
        self.mjai_messages = shared_queue

        # 存储活动的流及其对应的 Bridge
        self.activated_flows: list[str] = []
        self.bridges: dict[str, BaseBridge] = {}
        self.last_activity: dict[str, float] = {}  # flow_id -> 最近活动时间戳
        self.bridge_lock = threading.Lock()

        # 连接状态跟踪
        self._active_connections = 0

        # MajsoulMax mod state
        self._majsoulmax_enabled: bool = False
        self._majsoulmax_mod: object | None = None
        self._mod_liqi_protos: dict[str, object] = {}  # per-flow LiqiProto for MajsoulMax
        if local_settings.majsoulmax.mod_enable:
            self._init_majsoulmax()

    def _init_majsoulmax(self) -> None:
        """Initialise the MajsoulMax mod plugin.

        Attempts to update liqi proto files (liqi_pb2.py) if auto-update is
        configured, then imports and instantiates MajsoulMaxMod.
        """
        global _MAJSOULMAX_AVAILABLE

        # Optionally auto-update liqi proto files before importing the mod
        if _MAJSOULMAX_UPDATE_MODULE_AVAILABLE and local_settings.majsoulmax.liqi_auto_update:
            logger.info("[MITM] MajsoulMax: checking liqi proto file updates …")
            try:
                result = _majsoulmax_update_liqi.update(
                    local_settings.majsoulmax.liqi_version,
                    local_settings.majsoulmax.github_token,
                    local_settings.majsoulmax.liqi_hash,
                )
                # Persist the returned version/hash back to settings
                local_settings.majsoulmax.liqi_version = result.get("version", "")
                local_settings.majsoulmax.liqi_hash = result.get("hash", "")
            except Exception:
                logger.warning("[MITM] MajsoulMax: liqi update failed, using cached files (if any).")

        # Now import and instantiate the mod (requires liqi_pb2.py to exist)
        try:
            from akagi_ng.majsoulmax.liqi_new import LiqiProto as _mod_liqi_proto_class
            from akagi_ng.majsoulmax.mod import MajsoulMaxMod

            self._majsoulmax_mod = MajsoulMaxMod("akagi-integrated")
            self._mod_liqi_proto_class = _mod_liqi_proto_class
            _MAJSOULMAX_AVAILABLE = True
            self._majsoulmax_enabled = True
            logger.info("[MITM] MajsoulMax mod initialised successfully.")
        except ImportError as exc:
            if local_settings.majsoulmax.liqi_auto_update:
                hint = (
                    "liqi_auto_update is enabled but proto/liqi_pb2.py could not be "
                    "downloaded automatically (network error or GitHub API rate limit). "
                    "Check your network connection, add a GitHub token in Akagi settings, "
                    "or manually download liqi.json / liqi.proto / liqi_pb2.py from "
                    "https://github.com/Avenshy/AutoLiqi/releases/latest and place them "
                    "in akagi_ng/majsoulmax/proto/."
                )
            else:
                hint = (
                    "Ensure proto/liqi_pb2.py exists in akagi_ng/majsoulmax/proto/ "
                    "(enable liqi_auto_update or run update_liqi manually)."
                )
            logger.warning(f"[MITM] MajsoulMax mod is disabled: {exc}. {hint}")
        except Exception:
            logger.exception("[MITM] MajsoulMax mod failed to initialise.")

    def _enqueue_event(self, event: AkagiEvent) -> None:
        try:
            self.mjai_messages.put(event, block=False)
        except queue.Full:
            logger.warning(f"[MITM] MJAI message queue is full, dropping event: {event}")

    def _get_platform_for_flow(self, flow: mitmproxy.http.HTTPFlow) -> Platform | None:
        url = flow.request.url.lower()

        for platform, patterns in PLATFORM_URL_PATTERNS.items():
            if any(pattern in url for pattern in patterns):
                return platform

        return None

    def websocket_start(self, flow: mitmproxy.http.HTTPFlow) -> None:
        configured_platform = local_settings.platform
        detected_platform = self._get_platform_for_flow(flow)

        target_platform = configured_platform if configured_platform != Platform.AUTO else detected_platform

        if not target_platform:
            return

        platform = target_platform

        logger.info(f"[MITM] WebSocket connection opened: {flow.id} ({flow.request.url}) for {platform}")

        self.activated_flows.append(flow.id)
        with self.bridge_lock:
            match platform:
                case Platform.MAJSOUL:
                    self.bridges[flow.id] = MajsoulBridge()
                    # Create a per-flow MajsoulMax LiqiProto for request/response tracking
                    if self._majsoulmax_enabled and self._majsoulmax_mod is not None:
                        try:
                            self._mod_liqi_protos[flow.id] = self._mod_liqi_proto_class()
                        except Exception:
                            logger.exception("[MITM] MajsoulMax: failed to create LiqiProto for flow.")
                case Platform.TENHOU:
                    self.bridges[flow.id] = TenhouBridge()
                case Platform.AMATSUKI:
                    self.bridges[flow.id] = AmatsukiBridge()
                case Platform.RIICHI_CITY:
                    self.bridges[flow.id] = RiichiCityBridge()
                case _:
                    logger.error(f"Unsupported platform: {platform}")
                    return

            self.last_activity[flow.id] = time.time()
            # 更新连接计数并发送通知
            self._on_connection_established()

    def request(self, flow: mitmproxy.http.HTTPFlow):
        """处理 HTTP 请求"""
        # 如果是已知 WebSocket 流的 HTTP 握手或后续请求
        if flow.id in self.bridges:
            bridge = self.bridges[flow.id]
            if hasattr(bridge, "request"):
                bridge.request(flow)
            return

        # 否则尝试根据配置或 URL 探测平台
        configured_platform = local_settings.platform
        target_platform = configured_platform
        if target_platform == Platform.AUTO:
            target_platform = self._get_platform_for_flow(flow)

        if target_platform == Platform.AMATSUKI:
            # 天月平台特殊处理：即便没有 WebSocket 流也需要拦截心跳
            # 这里临时创建一个 Bridge 实例来处理（或者可以使用静态方法，但为了统一接口采用实例）
            AmatsukiBridge().request(flow)

    def response(self, flow: mitmproxy.http.HTTPFlow):
        """处理 HTTP 响应"""
        if flow.id in self.bridges:
            bridge = self.bridges[flow.id]
            if hasattr(bridge, "response"):
                bridge.response(flow)
            return

        configured_platform = local_settings.platform
        target_platform = configured_platform
        if target_platform == Platform.AUTO:
            target_platform = self._get_platform_for_flow(flow)

        if target_platform == Platform.AMATSUKI:
            AmatsukiBridge().response(flow)

    def _is_target_platform(self, flow: mitmproxy.http.HTTPFlow, platform: Platform) -> bool:
        url = flow.request.url.lower()
        patterns = PLATFORM_URL_PATTERNS.get(platform, [])
        return any(pattern in url for pattern in patterns) if patterns else True

    def _apply_majsoulmax_mod(self, flow: mitmproxy.http.HTTPFlow, msg: mitmproxy.websocket.WebSocketMessage) -> bool:
        """Run the MajsoulMax mod on *msg* (in-place) for the given flow.

        Returns True if the message was dropped (caller should return early),
        False otherwise.
        """
        mod_liqi_proto = self._mod_liqi_protos.get(flow.id)
        if mod_liqi_proto is None:
            return False
        try:
            from mitmproxy import ctx

            modify, drop, new_content, inject, inject_msg = self._majsoulmax_mod.main(  # type: ignore[union-attr]
                msg, mod_liqi_proto
            )
            if drop:
                msg.drop()
                return True
            if inject:
                ctx.master.commands.call("inject.websocket", flow, True, inject_msg, False)
            if modify:
                msg.content = new_content
        except Exception:
            logger.exception("[MITM] MajsoulMax mod error processing message.")
        return False

    def websocket_message(self, flow: mitmproxy.http.HTTPFlow) -> None:
        if flow.id not in self.activated_flows:
            return

        try:
            msg = flow.websocket.messages[-1]
            direction = "<-" if msg.from_client else "->"
            logger.trace(f"[MITM] {direction} Message: {msg.content}")

            # -------------------------------------------------------------------
            # MajsoulMax mod: intercept Majsoul messages before Akagi's bridge
            # Skips injected messages to prevent feedback loops.
            # -------------------------------------------------------------------
            if (
                self._majsoulmax_enabled
                and self._majsoulmax_mod is not None
                and not msg.injected
                and self._apply_majsoulmax_mod(flow, msg)
            ):
                return  # message was dropped

            # -------------------------------------------------------------------
            # Akagi bridge: parse for AI analysis
            # -------------------------------------------------------------------
            with self.bridge_lock:
                if flow.id not in self.bridges:
                    return
                bridge = self.bridges[flow.id]
                self.last_activity[flow.id] = time.time()
                msgs = bridge.parse(msg.content)

            if msgs:
                for m in msgs:
                    self._enqueue_event(m)

        except Exception:
            logger.exception("[MITM] Error parsing message")

    def _on_connection_established(self):
        """处理连接建立事件"""
        self._active_connections += 1
        is_first_connection = self._active_connections == 1

        # 只在第一个连接建立时发送通知
        if is_first_connection:
            self._enqueue_event(SystemEvent(code=NotificationCode.CLIENT_CONNECTED))
            logger.info("[MITM] Client connected (first connection)")

    def websocket_end(self, flow: mitmproxy.http.HTTPFlow) -> None:
        if flow.id in self.activated_flows:
            logger.info(f"[MITM] WebSocket connection closed: {flow.id}")
            self.activated_flows.remove(flow.id)
            with self.bridge_lock:
                if flow.id in self.bridges:
                    bridge = self.bridges[flow.id]
                    game_ended = getattr(bridge, "game_ended", False)
                    del self.bridges[flow.id]
                    self.last_activity.pop(flow.id, None)
                    # Clean up per-flow MajsoulMax LiqiProto
                    self._mod_liqi_protos.pop(flow.id, None)

                    # 更新连接计数并发送通知
                    self._on_connection_closed(game_ended)

    def _on_connection_closed(self, game_ended: bool):
        """处理连接关闭事件"""
        self._active_connections = max(0, self._active_connections - 1)
        all_connections_closed = self._active_connections == 0

        # 只在所有连接都关闭时发送断线通知
        if all_connections_closed:
            code = NotificationCode.RETURN_LOBBY if game_ended else NotificationCode.GAME_DISCONNECTED
            self._enqueue_event(SystemEvent(code=code))
            logger.info(f"[MITM] All connections closed, sending {code}")

    def _cleanup_stale_bridges(self, max_age_seconds: int = 300):
        """清理超过指定时间未活动的bridge"""
        current_time = time.time()
        with self.bridge_lock:
            for flow_id in list(self.bridges.keys()):
                # 情况1：已经在 activated_flows 之外（可能 websocket_end 没删干净）
                # 情况2：虽然在 activated_flows，但太久没说话了 (max_age_seconds)
                last_active = self.last_activity.get(flow_id, 0)
                is_stale = (current_time - last_active) > max_age_seconds

                if flow_id not in self.activated_flows or is_stale:
                    logger.warning(f"[MITM] Cleaning up stale bridge for flow {flow_id} (stale={is_stale})")
                    if flow_id in self.bridges:
                        del self.bridges[flow_id]
                    self.last_activity.pop(flow_id, None)
                    if flow_id in self.activated_flows:
                        self.activated_flows.remove(flow_id)
                        self._active_connections = max(0, self._active_connections - 1)
