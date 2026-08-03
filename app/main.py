"""Temir — 아이폰(리모컨)과 Tesla 브라우저(뷰어)를 클라우드 WebSocket으로 연결하는 서버.

모든 트래픽이 이 서버를 경유하므로 로컬 포트/핫스팟 제약 없이 동작한다.
룸 상태는 인메모리로만 유지한다 (HF Space 재시작 시 초기화).
"""

import asyncio
import io
import json
import secrets
import time

import qrcode
from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

ROOM_TTL_SECONDS = 3 * 3600          # 마지막 활동 후 3시간이 지난 룸은 정리
MAX_MEDIA_PER_ROOM = 30
MAX_FILE_BYTES = 8 * 1024 * 1024     # 업로드 파일당 8MB (클라이언트에서 리사이즈됨)
MAX_ROOM_MEDIA_BYTES = 60 * 1024 * 1024

app = FastAPI(title="Temir")

# 프론트엔드를 다른 곳(HF Static Space 등)에서 서빙하는 구성을 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Room:
    def __init__(self, code: str):
        self.code = code
        self.tv: WebSocket | None = None
        self.remotes: set[WebSocket] = set()
        # 마지막 화면 상태 — TV가 재접속해도 이어서 복원할 수 있게 서버에 보관
        self.state: dict = {"type": "scene", "scene": "idle", "payload": {}}
        self.media: dict[str, tuple[bytes, str]] = {}
        self.media_order: list[str] = []
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()

    @property
    def media_bytes(self) -> int:
        return sum(len(data) for data, _ in self.media.values())


rooms: dict[str, Room] = {}


def new_room() -> Room:
    while True:
        code = "".join(secrets.choice("0123456789") for _ in range(6))
        if code not in rooms:
            room = Room(code)
            rooms[code] = room
            return room


async def send_safe(ws: WebSocket, payload: dict):
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


async def broadcast_presence(room: Room):
    msg = {
        "type": "presence",
        "tvConnected": room.tv is not None,
        "remoteCount": len(room.remotes),
    }
    targets = list(room.remotes) + ([room.tv] if room.tv else [])
    for ws in targets:
        await send_safe(ws, msg)


@app.on_event("startup")
async def start_cleanup():
    async def cleanup_loop():
        while True:
            await asyncio.sleep(600)
            now = time.time()
            for code in [c for c, r in rooms.items() if now - r.last_active > ROOM_TTL_SECONDS]:
                rooms.pop(code, None)

    asyncio.create_task(cleanup_loop())


@app.post("/api/room")
async def create_room():
    room = new_room()
    return {"code": room.code}


@app.get("/api/room/{code}")
async def room_info(code: str):
    room = rooms.get(code)
    if not room:
        raise HTTPException(404, "room not found")
    return {
        "code": code,
        "tvConnected": room.tv is not None,
        "remoteCount": len(room.remotes),
    }


@app.get("/api/media/{code}")
async def list_media(code: str):
    room = rooms.get(code)
    if not room:
        raise HTTPException(404, "room not found")
    return {"items": [f"/media/{code}/{mid}" for mid in room.media_order]}


@app.post("/api/upload/{code}")
async def upload(code: str, file: UploadFile):
    room = rooms.get(code)
    if not room:
        raise HTTPException(404, "room not found")
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "file too large")
    # 용량 한도를 넘으면 오래된 것부터 정리
    while (room.media_bytes + len(data) > MAX_ROOM_MEDIA_BYTES
           or len(room.media_order) >= MAX_MEDIA_PER_ROOM):
        if not room.media_order:
            break
        oldest = room.media_order.pop(0)
        room.media.pop(oldest, None)
    media_id = secrets.token_urlsafe(8)
    room.media[media_id] = (data, file.content_type or "image/jpeg")
    room.media_order.append(media_id)
    room.touch()
    return {"id": media_id, "url": f"/media/{code}/{media_id}"}


@app.get("/media/{code}/{media_id}")
async def get_media(code: str, media_id: str):
    room = rooms.get(code)
    if not room or media_id not in room.media:
        raise HTTPException(404, "not found")
    data, content_type = room.media[media_id]
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=86400"})


@app.get("/qr/{code}.png")
async def qr_png(code: str, request: Request, target: str | None = None):
    # 프론트가 다른 호스트에 있으면 QR에 담을 리모컨 URL을 target으로 지정할 수 있다
    if target and target.startswith(("http://", "https://")):
        url = target
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        url = f"{proto}://{host}/remote?code={code}"
    img = qrcode.make(url, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.websocket("/ws/{code}")
async def ws_endpoint(ws: WebSocket, code: str, role: str = "remote"):
    await ws.accept()
    room = rooms.get(code)
    if not room:
        await send_safe(ws, {"type": "error", "error": "room-not-found"})
        await ws.close()
        return

    if role == "tv":
        # 기존 TV 연결이 남아 있으면 교체 (새로고침/재접속)
        if room.tv is not None:
            try:
                await room.tv.close()
            except Exception:
                pass
        room.tv = ws
    else:
        room.remotes.add(ws)

    room.touch()
    # 접속 직후 현재 화면 상태를 내려줘서 이어보기/동기화
    await send_safe(ws, {"type": "init", "state": room.state,
                         "media": [f"/media/{code}/{mid}" for mid in room.media_order]})
    await broadcast_presence(room)

    try:
        while True:
            raw = await ws.receive_text()
            room.touch()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")
            if mtype == "ping":
                await send_safe(ws, {"type": "pong"})
                continue

            if mtype == "scene":
                room.state = msg
                # 화면 전환은 TV와 (자신 외의) 모든 리모컨에 전파
                for peer in [room.tv, *room.remotes]:
                    if peer is not None and peer is not ws:
                        await send_safe(peer, msg)
            elif mtype == "control":
                if room.tv is not None:
                    await send_safe(room.tv, msg)
            elif mtype == "tv-event":
                for peer in room.remotes:
                    await send_safe(peer, msg)
    except WebSocketDisconnect:
        pass
    finally:
        if role == "tv":
            if room.tv is ws:
                room.tv = None
        else:
            room.remotes.discard(ws)
        await broadcast_presence(room)


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/tv")
async def tv_page():
    return FileResponse("static/tv.html")


@app.get("/remote")
async def remote_page():
    return FileResponse("static/remote.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
# tv.html / remote.html / config.js 같은 정적 경로도 루트에서 서빙 (HF Static Space와 경로 호환)
app.mount("/", StaticFiles(directory="static", html=True), name="root")
