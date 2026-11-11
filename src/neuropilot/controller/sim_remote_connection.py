# sim_remote_connection.py

import asyncio
import inspect
import socketio
import warnings


class Remote:
    """
    Simulation version of the pipeline Remote client.

    It keeps the same public API as remote_connection.py, but is intended
    to connect to the simulation relay server instead of the real relay.
    """

    FROM_EVENT = "from_external_controller"
    TO_EVENT = "to_external_controller"

    def __init__(self, url, topic_handlers=None, verbose=True):
        warnings.filterwarnings(
            "ignore",
            message="coroutine 'ClientWebSocketResponse.receive' was never awaited"
        )

        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,   # infinite retries
            reconnection_delay=1,
            reconnection_delay_max=5,
            logger=False,
            engineio_logger=False,
        )

        self.url = url
        self.topic_handlers = topic_handlers or {}
        self.verbose = verbose
        self.connected = False
        self._warned_disconnected = False

        # Incoming simulation messages for the pipeline
        self.sio.on(self.TO_EVENT, self.on_message_received)

        # Optional lifecycle hooks
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("connect_error", self._on_connect_error)

    def register_handler(self, topic, func):
        self.topic_handlers[topic] = func

    def register_handlers(self, handlers):
        for topic, func in handlers.items():
            self.topic_handlers[topic] = func

    async def connect(self):
        if self.connected:
            return

        await self.sio.connect(self.url)
        asyncio.create_task(self.sio.wait())

    async def disconnect(self):
        if self.sio.connected:
            await self.sio.disconnect()

    async def send_message(self, topic, data=None):
        if data is None:
            data = {}

        message = {
            "topic": topic,
            "data": data,
        }

        if not self.sio.connected:
            # Callers fire-and-forget via create_task, so raising here only
            # produces lost messages and unhandled-task-exception noise. Drop
            # the message instead; the client reconnects automatically.
            if self.verbose and not self._warned_disconnected:
                print(f"[SIM REMOTE] Not connected to relay at {self.url} -- "
                      f"dropping message '{topic}'")
                self._warned_disconnected = True
            return False

        if self.verbose:
            print(f"[SIM REMOTE] pipeline -> relay | {topic} | {data}")

        try:
            await self.sio.emit(self.FROM_EVENT, message)
        except socketio.exceptions.BadNamespaceError:
            # Disconnected between the check and the emit.
            if self.verbose and not self._warned_disconnected:
                print(f"[SIM REMOTE] Not connected to relay at {self.url} -- "
                      f"dropping message '{topic}'")
                self._warned_disconnected = True
            return False
        return True

    async def on_message_received(self, data):
        # The relay forwards whatever a client published; a malformed frame
        # must not raise inside the socket handler.
        if not isinstance(data, dict):
            if self.verbose:
                print(f"[SIM REMOTE] ignoring non-object message: {type(data).__name__}")
            return
        topic = data.get("topic")
        payload = data.get("data")

        if self.verbose:
            #print(f"[SIM REMOTE] relay -> pipeline | {topic} | {payload}")
            pass

        handler = self.topic_handlers.get(topic)

        if handler is None:
            if self.verbose:
                #print(f"[SIM REMOTE] No handler defined for topic: {topic}")
                pass
            return

        result = handler(payload)
        if inspect.isawaitable(result):
            await result

    async def _on_connect(self):
        self.connected = True
        self._warned_disconnected = False
        if self.verbose:
            print(f"[SIM REMOTE] Connected to simulation relay at {self.url}")

    async def _on_disconnect(self):
        self.connected = False
        if self.verbose:
            print("[SIM REMOTE] Disconnected from simulation relay")

    async def _on_connect_error(self, data):
        self.connected = False
        print(f"[SIM REMOTE] Connection error to {self.url}: {data}")

    def is_connected(self):
        return self.connected