"""Relay client for real-hardware operation: connects the controller to the
production Socket.IO relay server (tms-robot-control ``relay_server.py``)
over the external-controller channel.

The relay re-routes the ``from_external_controller`` / ``to_external_controller``
events between the components; a message carries ``{"topic": str,
"data": dict}``. Incoming messages are dispatched by topic to handlers
registered by the ``PipelineController`` (:meth:`Remote.register_handlers`);
outgoing messages are fire-and-forget — sends while disconnected are
dropped with a one-time warning instead of raising, because the senders run
as background tasks where a raise would only produce lost messages and
unhandled-exception noise. The client reconnects automatically and
indefinitely (1–5 s backoff), so relay restarts recover without operator
action.

The simulated stack uses the identical interface in
``neuropilot.controller.sim_remote_connection``.
"""

import socketio
import asyncio
import inspect
import warnings


class Remote:
    """Asynchronous Socket.IO client for the external-controller relay channel."""

    def __init__(self, url, topic_handlers=None):
        """Connect to the relay at ``url`` and subscribe to incoming messages.

        ``topic_handlers`` optionally maps topic names to async callables
        (``async def handler(payload_dict)``); more can be added later via
        :meth:`register_handler` / :meth:`register_handlers`.
        """
        warnings.filterwarnings("ignore", message="coroutine 'ClientWebSocketResponse.receive' was never awaited")
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,   # infinite retries
            reconnection_delay=1,
            reconnection_delay_max=5,
        )
        self.url = url
        self.topic_handlers = topic_handlers or {}
        self._warned_disconnected = False

        # Report the connection lifecycle so relay restarts are visible.
        self.sio.on('connect', self._on_connect)
        self.sio.on('disconnect', self._on_disconnect)

        # Register one generic handler
        self.sio.on('to_external_controller', self.on_message_received)

    def register_handler(self, topic, func):
        """Register ``func`` as the handler for messages with ``topic``."""
        self.topic_handlers[topic] = func

    def register_handlers(self, handlers):
        """Register a ``{topic: handler}`` mapping in one call."""
        for topic, func in handlers.items():
            self.topic_handlers[topic] = func

    async def connect(self):
        """Connect to the relay and keep the connection alive.

        The controller can start before the relay (for example when the
        operator presses Start relay on the Connections page), so the initial
        connection is retried until the relay is reachable. ``sio.wait()``
        then runs as a background task; reconnects after a relay restart are
        handled by Socket.IO.
        """
        while True:
            try:
                await self.sio.connect(self.url)
                break
            except Exception as e:
                if not self._warned_disconnected:
                    print(f"[REMOTE] waiting for relay at {self.url}: {e}")
                    self._warned_disconnected = True
                await asyncio.sleep(2)
        asyncio.create_task(self.sio.wait())

    async def send_message(self, topic, data=None):
        """Emit a ``from_external_controller`` message; return True on success.

        Messages sent while disconnected are dropped (with a warning once
        per outage) rather than raised — see the module docstring.
        """
        if data is None:
            data = {}

        message = {
            'topic': topic,
            'data': data
        }

        # Callers fire-and-forget via create_task, so raising here only
        # produces lost messages and unhandled-task-exception noise. Drop
        # the message instead; the client reconnects automatically.
        if not self.sio.connected:
            self._warn_dropped(topic)
            return False

        try:
            await self.sio.emit('from_external_controller', message)
        except socketio.exceptions.BadNamespaceError:
            # Disconnected between the check and the emit.
            self._warn_dropped(topic)
            return False
        return True

    def _warn_dropped(self, topic):
        # Warn once per outage, not once per message.
        if not self._warned_disconnected:
            print(f"[REMOTE] Not connected to relay at {self.url} -- "
                  f"dropping message '{topic}' (reconnecting)")
            self._warned_disconnected = True

    def _on_connect(self):
        self._warned_disconnected = False
        print(f"[REMOTE] Connected to relay at {self.url}")

    def _on_disconnect(self):
        print(f"[REMOTE] Disconnected from relay at {self.url} -- reconnecting")

    async def on_message_received(self, data):
        """Dispatch one relay message to the handler registered for its topic.

        Handlers may be plain functions (most controller callbacks) or
        coroutines; awaiting a plain function's return value used to raise
        ``TypeError`` per message, and a non-object frame raised in the
        socket.io receive task.
        """
        if not isinstance(data, dict):
            print(f"[REMOTE] ignoring non-object message: {type(data).__name__}")
            return
        topic = data.get('topic')
        payload = data.get('data')

        handler = self.topic_handlers.get(topic)
        if handler is None:
            # Optionally log or handle the missing topic handler
            print(f"No handler defined for topic: {topic}")
            return
        result = handler(payload)
        if inspect.isawaitable(result):
            await result
