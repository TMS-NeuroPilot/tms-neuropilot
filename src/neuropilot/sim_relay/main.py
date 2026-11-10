#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
from datetime import datetime

import nest_asyncio
import socketio
import uvicorn

nest_asyncio.apply()

default_host = "127.0.0.1"
default_port = 5000

if len(sys.argv) == 3:
    host = sys.argv[1]
    port = int(sys.argv[2])
elif len(sys.argv) == 2:
    host = default_host
    port = int(sys.argv[1])
else:
    host = default_host
    port = default_port


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
)
app = socketio.ASGIApp(sio)

client_roles = {}


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg):
    print(f"[{ts()}][SIM RELAY] {msg}")


@sio.event
async def connect(sid, environ, auth):
    role = None
    if auth and isinstance(auth, dict):
        role = auth.get("role")

    client_roles[sid] = role or "unknown"
    log(f"Client connected: sid={sid}, role={client_roles[sid]}")


@sio.event
async def disconnect(sid):
    role = client_roles.pop(sid, "unknown")
    log(f"Client disconnected: sid={sid}, role={role}")


@sio.event
async def register_role(sid, data):
    role = "unknown"
    if isinstance(data, dict):
        role = data.get("role", "unknown")
    client_roles[sid] = role
    log(f"Registered role: sid={sid}, role={role}")


@sio.event
async def from_neuronavigation(sid, msg):
    await sio.emit("to_robot", msg)
    await sio.emit("to_external_controller", msg)
    log(f"Forwarding neuronavigation -> robot and pipeline: {msg}")


@sio.event
async def from_robot(sid, msg):
    await sio.emit("to_neuronavigation", msg)
    await sio.emit("to_external_controller", msg)

    topic = None
    if isinstance(msg, dict):
        topic = msg.get("topic")

    if topic and "Health status" in topic:
        return

    log(f"Forwarding robot -> neuronavigation and pipeline: {msg}")


@sio.event
async def from_external_controller(sid, msg):
    await sio.emit("to_neuronavigation", msg)
    await sio.emit("to_robot", msg)
    log(f"Forwarding pipeline -> neuronavigation and robot: {msg}")


@sio.event
async def restart_robot_main_loop(sid):
    await sio.emit("restart_robot_main_loop")
    log("Restarting robot main_loop")


def run():
    log(f"Starting simulation relay on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, loop="asyncio")


if __name__ == "__main__":
    run()