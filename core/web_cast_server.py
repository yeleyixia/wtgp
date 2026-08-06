import asyncio
import json
import time
import uuid
import struct
import base64
import threading
import socket
from typing import Dict, Set, Optional, List
from collections import defaultdict
from PySide6.QtCore import QObject, Signal

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    HAS_HTTP = True
except ImportError:
    HAS_HTTP = False


DEVICE_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>为投个屏 - __DEVICE_ID__</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0f0f0f; color: #fff; min-height: 100vh;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
        }
        .device-frame {
            width: 380px; height: 820px;
            background: #1a1a1a; border-radius: 40px;
            border: 2px solid #333; overflow: hidden; position: relative;
            box-shadow: 0 0 60px rgba(59, 130, 246, 0.3);
        }
        #video { width: 100%; height: 100%; object-fit: cover; background: #000; }
        .controls { margin-top: 20px; display: flex; gap: 10px; }
        .controls button {
            padding: 10px 20px; background: #3b82f6; color: white; border: none;
            border-radius: 8px; cursor: pointer; font-size: 14px;
        }
        .controls button:hover { background: #2563eb; }
        .info { color: #666; font-size: 12px; margin-top: 10px; }
        .toast {
            position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
            background: rgba(0,0,0,0.8); color: white; padding: 10px 20px;
            border-radius: 8px; opacity: 0; transition: opacity 0.3s;
        }
        .toast.show { opacity: 1; }
    </style>
</head>
<body>
    <div class="device-frame">
        <canvas id="video" width="1080" height="2400"></canvas>
    </div>
    <div class="controls">__CTRL_BUTTONS__
    </div>
    <div class="info">设备: __DEVICE_ID__ | 权限: __PERMISSION_TEXT__</div>
    <div class="toast" id="toast"></div>
    <script>
        const canvas = document.getElementById('video');
        const ctx = canvas.getContext('2d');
        const ws = new WebSocket('ws://' + window.location.hostname + ':8081');

        ws.onopen = () => {
            ws.send(JSON.stringify({type: 'join', token: '__TOKEN__'}));
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'frame') {
                    const img = new Image();
                    img.onload = () => {
                        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    };
                    img.src = 'data:image/jpeg;base64,' + data.frame;
                } else if (data.type === 'error') {
                    showToast(data.message);
                }
            } catch(e) {}
        };

        function sendControl(action) {
            ws.send(JSON.stringify({
                type: 'control',
                token: '__TOKEN__',
                data: {action: action}
            }));
        }

        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        canvas.addEventListener('click', (e) => {
__CTRL_JS__
        });
    </script>
</body>
</html>"""


class PermissionManager:
    def __init__(self):
        self._permissions: Dict[str, dict] = {}
        self._groups: Dict[str, list] = {}
        self._templates: Dict[str, dict] = {}
        self._init_templates()

    def _init_templates(self):
        self._templates = {
            "view_only": {
                "name": "仅查看",
                "can_view": True,
                "can_control": False,
                "can_clipboard": False,
                "max_viewers": 1,
                "expiry_hours": 24,
            },
            "standard": {
                "name": "标准",
                "can_view": True,
                "can_control": True,
                "can_clipboard": True,
                "max_viewers": 5,
                "expiry_hours": 72,
            },
            "full_control": {
                "name": "完全控制",
                "can_view": True,
                "can_control": True,
                "can_clipboard": True,
                "max_viewers": 10,
                "expiry_hours": 168,
            },
        }

    def create_share_token(self, device_id: str, template_name: str = "standard",
                           expiry_hours: int = None) -> dict:
        template = self._templates.get(template_name, self._templates["standard"])
        token = str(uuid.uuid4())
        if expiry_hours is None:
            expiry_hours = template["expiry_hours"]
        self._permissions[token] = {
            "device_id": device_id,
            "permissions": template.copy(),
            "created_at": time.time(),
            "expires_at": time.time() + expiry_hours * 3600,
            "viewers": set(),
            "status": "active",
        }
        return {
            "token": token,
            "url": f"http://localhost:8080/device/{token}",
            "expires_in_hours": expiry_hours,
            "permissions": template,
        }

    def validate_token(self, token: str) -> Optional[dict]:
        if token not in self._permissions:
            return None
        perm = self._permissions[token]
        if perm["status"] != "active":
            return None
        if time.time() > perm["expires_at"]:
            perm["status"] = "expired"
            return None
        return perm

    def add_viewer(self, token: str, viewer_id: str) -> bool:
        perm = self.validate_token(token)
        if not perm:
            return False
        if len(perm["viewers"]) >= perm["permissions"]["max_viewers"]:
            return False
        perm["viewers"].add(viewer_id)
        return True

    def remove_viewer(self, token: str, viewer_id: str):
        if token in self._permissions:
            self._permissions[token]["viewers"].discard(viewer_id)

    def revoke_token(self, token: str):
        if token in self._permissions:
            self._permissions[token]["status"] = "revoked"

    def create_device_group(self, name: str, device_ids: List[str]) -> str:
        group_id = str(uuid.uuid4())
        self._groups[group_id] = {
            "name": name,
            "device_ids": device_ids,
            "created_at": time.time(),
        }
        return group_id

    def get_group(self, group_id: str) -> Optional[dict]:
        return self._groups.get(group_id)

    def list_groups(self) -> list:
        return [{"id": gid, **info} for gid, info in self._groups.items()]

    def list_permissions(self) -> list:
        result = []
        for token, perm in self._permissions.items():
            result.append({
                "token": token,
                "device_id": perm["device_id"],
                "status": perm["status"],
                "viewers_count": len(perm["viewers"]),
                "expires_at": perm["expires_at"],
            })
        return result


class WebCastServer(QObject):
    client_connected = Signal(str, str)
    client_disconnected = Signal(str)
    frame_broadcast = Signal(bytes)
    stats_updated = Signal(dict)

    def __init__(self, host: str = "127.0.0.1", port: int = 8080, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._running = False
        self._http_server = None
        self._http_thread: Optional[threading.Thread] = None
        self._ws_server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_server = None
        self._ws_stop_event = None
        self._clients: Dict[str, Set] = defaultdict(set)
        self._client_sockets: Dict[str, object] = {}
        self._client_futures: Dict[str, object] = {}
        self._client_tokens: Dict[str, str] = {}
        self._frames: Dict[str, bytes] = {}
        self._permission_mgr = PermissionManager()
        self._frame_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._latest_frames: Dict[str, bytes] = {}
        self._devices: Dict[str, dict] = {}

    @property
    def permission_manager(self) -> PermissionManager:
        return self._permission_mgr

    def register_device(self, device_id: str, info: dict):
        with self._lock:
            self._devices[device_id] = info

    def unregister_device(self, device_id: str):
        with self._lock:
            if device_id in self._devices:
                del self._devices[device_id]

    def update_device_frame(self, device_id: str, frame_data: bytes):
        with self._lock:
            self._latest_frames[device_id] = frame_data

    def start(self):
        if self._running:
            return False
        self._running = True

        if HAS_HTTP:
            self._http_thread = threading.Thread(target=self._start_http_server, daemon=True)
            self._http_thread.start()

        if HAS_WEBSOCKETS:
            self._ws_thread = threading.Thread(target=self._run_ws_server, daemon=True)
            self._ws_thread.start()

        self._frame_thread = threading.Thread(target=self._frame_broadcast_loop, daemon=True)
        self._frame_thread.start()

        return True

    def stop(self):
        self._running = False
        if self._http_server:
            try:
                self._http_server.shutdown()
            except Exception:
                pass
            self._http_server = None
        if self._http_thread:
            try:
                self._http_thread.join(timeout=3)
            except Exception:
                pass
        if self._loop and not self._loop.is_closed():
            # 先关闭 WebSocket 服务端，再停事件循环，避免半开的连接和告警
            if self._ws_server is not None:
                try:
                    self._loop.call_soon_threadsafe(self._ws_server.close)
                except Exception:
                    pass
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._ws_server.wait_closed(), self._loop
                    ).result(timeout=2)
                except Exception:
                    pass
                self._ws_server = None
            # 让 _start_ws 里的 wait 正常返回，避免事件循环停止时的告警
            if self._ws_stop_event is not None:
                try:
                    self._loop.call_soon_threadsafe(self._ws_stop_event.set)
                except Exception:
                    pass
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        if self._ws_thread:
            try:
                self._ws_thread.join(timeout=3)
            except Exception:
                pass
        if self._frame_thread:
            try:
                self._frame_thread.join(timeout=2)
            except Exception:
                pass

    def _start_http_server(self):
        class WebHandler(BaseHTTPRequestHandler):
            server_ref = self

            def do_GET(self):
                path = self.path.rstrip('/')
                if path == '/' or path == '':
                    self._send_html(self._index_page())
                elif path.startswith('/device/'):
                    token = path.split('/device/')[1]
                    perm = self.server_ref._permission_mgr.validate_token(token)
                    if perm:
                        self._send_html(self._device_page(perm, token))
                    else:
                        self._send_error(404, "分享链接已失效")
                elif path.startswith('/api/'):
                    self._handle_api(path)
                elif path == '/health':
                    self._send_json({"status": "ok"})
                else:
                    self._send_error(404, "Not Found")

            def _send_html(self, html: str):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))

            def _send_json(self, data: dict):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))

            def _send_error(self, code: int, msg: str):
                self.send_response(code)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(msg.encode('utf-8'))

            def _handle_api(self, path: str):
                parts = path.split('/')
                if len(parts) >= 3 and parts[2] == 'devices':
                    devices = list(self.server_ref._devices.values())
                    self._send_json({"devices": devices})
                elif len(parts) >= 3 and parts[2] == 'status':
                    active_clients = sum(len(v) for v in self.server_ref._clients.values())
                    self._send_json({
                        "status": "running",
                        "active_connections": active_clients,
                        "devices_count": len(self.server_ref._devices),
                    })
                else:
                    self._send_json({"error": "Unknown API endpoint"})

            def log_message(self, format, *args):
                pass

        try:
            self._http_server = HTTPServer((self._host, self._port), WebHandler)
            self._http_server.timeout = 0.5
            self._http_server.serve_forever(poll_interval=0.5)
        except Exception as e:
            print(f"HTTP server error: {e}")

    def _run_ws_server(self):
        if not HAS_WEBSOCKETS:
            return
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            # 以任务方式运行，避免 run_until_complete 结束后再 run_forever
            # 造成的停止顺序问题
            self._loop.create_task(self._start_ws())
            self._loop.run_forever()
            # 收尾：取消剩余任务并关闭循环
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass
        except Exception as e:
            print(f"WebSocket server error: {e}")

    async def _start_ws(self):
        self._ws_server = await websockets.serve(
            self._ws_handler,
            self._host,
            self._port + 1,
            ping_interval=30,
            ping_timeout=10,
        )
        print(f"WebSocket server running on ws://{self._host}:{self._port + 1}")
        self._ws_stop_event = asyncio.Event()
        await self._ws_stop_event.wait()

    async def _ws_handler(self, websocket):
        client_id = str(uuid.uuid4())[:8]
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    if msg_type == "join":
                        token = data.get("token", "")
                        perm = self._permission_mgr.validate_token(token)
                        if perm:
                            device_id = perm["device_id"]
                            if self._permission_mgr.add_viewer(token, client_id):
                                self._clients[device_id].add(client_id)
                                self._client_sockets[client_id] = websocket
                                self._client_tokens[client_id] = token
                                self.client_connected.emit(client_id, device_id)
                                await websocket.send(json.dumps({
                                    "type": "joined",
                                    "device_id": device_id,
                                    "permissions": perm["permissions"],
                                }))
                            else:
                                await websocket.send(json.dumps({
                                    "type": "error",
                                    "message": "已达到最大观看人数",
                                }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "无效或已过期的分享链接",
                            }))

                    elif msg_type == "control":
                        token = data.get("token", "")
                        perm = self._permission_mgr.validate_token(token)
                        if perm and perm["permissions"]["can_control"]:
                            device_id = perm["device_id"]
                            control_data = data.get("data", {})
                            self.frame_broadcast.emit(json.dumps({
                                "device_id": device_id,
                                "control": control_data,
                                "client_id": client_id,
                            }).encode())

                    elif msg_type == "clipboard":
                        token = data.get("token", "")
                        text = data.get("text", "")
                        perm = self._permission_mgr.validate_token(token)
                        if perm and perm["permissions"]["can_clipboard"]:
                            self.frame_broadcast.emit(json.dumps({
                                "type": "clipboard",
                                "text": text,
                                "client_id": client_id,
                            }).encode())

                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            for device_id in list(self._clients.keys()):
                self._clients[device_id].discard(client_id)
            self._client_sockets.pop(client_id, None)
            self._client_futures.pop(client_id, None)
            self._client_tokens.pop(client_id, None)
            self.client_disconnected.emit(client_id)

    def _frame_broadcast_loop(self):
        while self._running:
            try:
                with self._lock:
                    frames_copy = dict(self._latest_frames)
                    clients_copy = {k: set(v) for k, v in self._clients.items()}

                if self._loop is None or self._loop.is_closed():
                    time.sleep(0.05)
                    continue

                for device_id, viewers in clients_copy.items():
                    frame_data = frames_copy.get(device_id)
                    if not frame_data or not viewers:
                        continue

                    payload = None
                    for viewer_id in list(viewers):
                        websocket = self._client_sockets.get(viewer_id)
                        if websocket is None:
                            continue
                        # 上一帧还没发完（发送慢于帧率），跳过本帧防止积压
                        pending = self._client_futures.get(viewer_id)
                        if pending is not None and not pending.done():
                            continue
                        if payload is None:
                            payload = json.dumps({
                                "type": "frame",
                                "device_id": device_id,
                                "frame": base64.b64encode(frame_data).decode("ascii"),
                            })
                        try:
                            fut = asyncio.run_coroutine_threadsafe(
                                self._send_text(websocket, payload), self._loop
                            )
                        except Exception:
                            self._drop_viewer(viewer_id)
                            continue
                        self._client_futures[viewer_id] = fut
                        fut.add_done_callback(
                            lambda f, vid=viewer_id: self._on_frame_sent(vid, f)
                        )

                time.sleep(0.033)
            except Exception:
                time.sleep(0.1)

    async def _send_text(self, websocket, text: str):
        await websocket.send(text)

    def _on_frame_sent(self, viewer_id: str, future):
        if future.exception() is not None:
            # 发送失败：连接已断开，清理该客户端
            self._drop_viewer(viewer_id)
        else:
            self._client_futures.pop(viewer_id, None)

    def _drop_viewer(self, viewer_id: str):
        """移除断开的 WebSocket 客户端"""
        self._client_futures.pop(viewer_id, None)
        token = self._client_tokens.pop(viewer_id, None)
        ws = self._client_sockets.pop(viewer_id, None)
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        for device_id, viewers in list(self._clients.items()):
            if viewer_id in viewers:
                viewers.discard(viewer_id)
                if token:
                    self._permission_mgr.remove_viewer(token, viewer_id)
        self.client_disconnected.emit(viewer_id)

    def _index_page(self) -> str:
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>为投个屏 - 投屏服务</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center;
        }
        .container { text-align: center; padding: 40px; }
        h1 { font-size: 2.5em; margin-bottom: 20px; background: linear-gradient(90deg, #3b82f6, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        p { color: #aaa; font-size: 1.1em; margin-bottom: 30px; }
        .status {
            display: inline-block; padding: 8px 20px; border-radius: 20px;
            background: rgba(59, 130, 246, 0.2); border: 1px solid rgba(59, 130, 246, 0.3);
            color: #60a5fa;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 为投个屏</h1>
        <p>HarmonyOS 投屏服务正在运行</p>
        <div class="status">● 服务在线</div>
    </div>
</body>
</html>"""

    def _device_page(self, perm: dict, token: str) -> str:
        device_id = perm["device_id"]
        can_control = perm["permissions"]["can_control"]
        ctrl_buttons = ""
        if can_control:
            ctrl_buttons = """
        <button onclick='sendControl("back")'>返回</button>
        <button onclick='sendControl("home")'>主页</button>
        <button onclick='sendControl("recent")'>多任务</button>"""
        ctrl_js = ""
        if can_control:
            ctrl_js = """
            if (ws.readyState === 1) {
                const rect = canvas.getBoundingClientRect();
                const x = Math.round((e.clientX - rect.left) / rect.width * 1080);
                const y = Math.round((e.clientY - rect.top) / rect.height * 2400);
                ws.send(JSON.stringify({type: 'control', token: '__TOKEN__', data: {action: 'touch', x, y}}));
            }"""
        permission_text = "完全控制" if can_control else "仅查看"

        html = DEVICE_PAGE_TEMPLATE
        html = html.replace("__DEVICE_ID__", device_id)
        html = html.replace("__TOKEN__", token)
        html = html.replace("__CTRL_BUTTONS__", ctrl_buttons)
        html = html.replace("__CTRL_JS__", ctrl_js)
        html = html.replace("__PERMISSION_TEXT__", permission_text)
        return html
