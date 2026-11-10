#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Simulated relay hub: a minimal stand-in for the production relay server
(tms-robot-control ``relay_server.py``) that connects the simulated stack.

Launched as ``python -m neuropilot.sim_relay`` (the ``neuropilot sim``
supervisor starts it first; the other components connect to it). Address:
``[host] [port]`` positional arguments, default ``127.0.0.1 5000``.

Routing mirrors the production relay: every message (``{"topic": str,
"data": dict}``) sent to a ``from_*`` event is re-emitted as ``to_*`` to the
other roles —

    from_neuronavigation    -> to_robot + to_external_controller
    from_robot              -> to_neuronavigation + to_external_controller
    from_external_controller-> to_neuronavigation + to_robot

Clients identify themselves via a ``register_role`` event (or an ``auth``
payload at connect time) purely for logging. High-frequency ``Health
status`` messages are forwarded but not logged. ``restart_robot_main_loop``
is re-broadcast so the supervisor can restart the robot process.
"""

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
    """Log new clients; the role comes from the Socket.IO auth payload."""
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
    """Clients can (re)declare their role after connecting."""
    role = "unknown"
    if isinstance(data, dict):
        role = data.get("role", "unknown")
    client_roles[sid] = role
    log(f"Registered role: sid={sid}, role={role}")


@sio.event
async def from_neuronavigation(sid, msg):
    """Neuronavigation output goes to the robot and the pipeline."""
    await sio.emit("to_robot", msg)
    await sio.emit("to_external_controller", msg)
    log(f"Forwarding neuronavigation -> robot and pipeline: {msg}")


@sio.event
async def from_robot(sid, msg):
    """Robot output goes to the neuronavigation and the pipeline.

    Health status messages are forwarded but not logged (they arrive at
    high frequency and would flood the console).
    """
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
    """Pipeline output goes to the neuronavigation and the robot."""
    await sio.emit("to_neuronavigation", msg)
    await sio.emit("to_robot", msg)
    log(f"Forwarding pipeline -> neuronavigation and robot: {msg}")


@sio.event
async def restart_robot_main_loop(sid):
    """Re-broadcast the restart request for the (virtual) robot main loop."""
    await sio.emit("restart_robot_main_loop")
    log("Restarting robot main_loop")


def run():
    """Serve the relay with uvicorn (ASGI, plain asyncio loop)."""
    log(f"Starting simulation relay on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, loop="asyncio")


if __name__ == "__main__":
    run()