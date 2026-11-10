"""Streams overview frames of the MuJoCo scene to the pipeline GUI.

A fixed camera in the composed scene (``gui_cam``) is rendered offscreen at
a low rate; frames are JPEG-encoded and published on
``SIM - Robot to Pipeline: Camera frame``. The GUI decodes them into the
robot view panel below the logger. Sends drop silently while disconnected
(fire-and-forget, like all senders).
"""

import asyncio
import base64
import io
import threading
import time

from . import config
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class CameraStreamer:
    """Renders the ``gui_cam`` camera at ``CAMERA_STREAM_FPS`` and publishes
    JPEG frames through the relay client. Runs on a daemon thread; the async
    emit is scheduled back onto the client's event loop."""

    def __init__(self, world, client):
        self.world = world
        self.client = client
        self._renderer = None
        self._renderer_model = None  # model the renderer was built for
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="camera-streamer")

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _ensure_renderer(self):
        """(Re)create the offscreen renderer when the model was rebuilt
        (e.g. after a head-mesh reload)."""
        import mujoco
        if self._renderer is None or self._renderer_model is not self.world.model:
            if self._renderer is not None:
                self._renderer.close()
            self._renderer = mujoco.Renderer(
                self.world.model,
                height=config.CAMERA_STREAM_HEIGHT,
                width=config.CAMERA_STREAM_WIDTH,
            )
            self._renderer_model = self.world.model

    def _run(self):
        import mujoco
        interval = 1.0 / config.CAMERA_STREAM_FPS
        log.info("GUI camera stream started")
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._ensure_renderer()
                with self.world._data_lock:
                    self._renderer.update_scene(self.world.data,
                                                camera=config.GUI_CAMERA_NAME)
                    frame = self._renderer.render()
                self._publish(frame)
            except Exception as e:
                log.debug(f"Camera stream skipped a frame: {e}")
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, interval - elapsed))
        if self._renderer is not None:
            self._renderer.close()
        log.info("GUI camera stream stopped")

    def _publish(self, frame):
        """JPEG-encode and schedule the emit on the client's event loop."""
        from PIL import Image

        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=config.CAMERA_STREAM_QUALITY)
        payload = base64.b64encode(buf.getvalue()).decode("ascii")
        loop = self.client.loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(
            self.client.send_message(config.TOPIC_CAMERA_FRAME,
                                     {"jpeg": payload, "width": frame.shape[1],
                                      "height": frame.shape[0]}),
            loop,
        )
