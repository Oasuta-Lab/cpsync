"""
Clipboard Sync - WebSocket Server
-----------------------------------
Relays clipboard content from iPad to Windows.
Uses aiohttp to handle both HTTP health checks and WebSocket connections.

Requirements:
    pip install aiohttp

Run locally:
    python server.py
"""

import asyncio
import os
from collections import defaultdict
from urllib.parse import parse_qs

from aiohttp import WSMsgType, web

# Rooms: dict of room_id -> set of connected WebSocket responses
rooms: dict[str, set] = defaultdict(set)


async def health(request):
    return web.Response(text="OK")


async def websocket_handler(request):
    """Handle WebSocket connections."""
    # Extract room ID from query string
    room_id = request.rel_url.query.get("room")

    if not room_id:
        return web.Response(status=400, text="Missing room parameter")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    rooms[room_id].add(ws)
    print(f"[+] Connected | room={room_id} | peers={len(rooms[room_id])}")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                text = msg.data.strip()
                if text:
                    print(f"[→] Relaying {len(text)} chars to room={room_id}")
                    peers = rooms[room_id] - {ws}
                    if peers:
                        await asyncio.gather(*[peer.send_str(text) for peer in peers])
                    else:
                        print("    (no peers in room yet)")
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        rooms[room_id].discard(ws)
        if not rooms[room_id]:
            del rooms[room_id]
        print(f"[-] Disconnected | room={room_id}")

    return ws


async def main():
    port = int(os.environ.get("PORT", 8765))

    app = web.Application()
    app.router.add_get("/", health)  # Health check endpoint
    app.router.add_get("/ws", websocket_handler)  # WebSocket endpoint

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"🚀 Server running on 0.0.0.0:{port}")

    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
