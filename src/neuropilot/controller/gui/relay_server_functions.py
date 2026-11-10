
import socketio

class RelayServerRemote:
    def __init__(self, url, topic_handlers=None):
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
        self.sio.on('to_robot', self.on_message_received)

    def register_handler(self, topic, func):
        self.topic_handlers[topic] = func

    def register_handlers(self, handlers):
        for topic, func in handlers.items():
            self.topic_handlers[topic] = func

    async def connect(self):
        await self.sio.connect(self.url)

    async def send_message(self, topic, data=None):
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
            await self.sio.emit('from_robot', message)
        except socketio.exceptions.BadNamespaceError:
            # Disconnected between the check and the emit.
            self._warn_dropped(topic)
            return False
        return True

    def _warn_dropped(self, topic):
        # Warn once per outage, not once per message.
        if not self._warned_disconnected:
            print(f"[RELAY] Not connected to relay at {self.url} -- "
                  f"dropping message '{topic}' (reconnecting)")
            self._warned_disconnected = True

    def _on_connect(self):
        self._warned_disconnected = False
        print(f"[RELAY] Connected to relay at {self.url}")

    def _on_disconnect(self):
        print(f"[RELAY] Disconnected from relay at {self.url} -- reconnecting")

    async def on_message_received(self, data):
        topic = data.get('topic')
        payload = data.get('data')
        if topic in self.topic_handlers:
            if self.topic_handlers[topic] is not None:
                await self.topic_handlers[topic](payload)
            else:
                # Optionally log or handle the missing topic handler
                print(f"No handler defined for topic: {topic}")
