# Relay protocol

All components speak one protocol: a Socket.IO event, a topic string and a small
JSON payload. This page is the readable contract; `tests/test_relay_topics.py`
is the executable one.

## Envelope

```json
{
  "topic": "Neuronavigation to Robot: Set target",
  "data": { "position": [x, y, z], "orientation": [rx, ry, rz] }
}
```

Units are **millimetres and degrees** (XYZ Euler, `sxyz`) unless a field says
otherwise — see [Units and frames](start/units.md).

## Routing

| Event published by | Routed to |
|---|---|
| `from_external_controller` | `to_neuronavigation` + `to_robot` |
| `from_neuronavigation` | `to_robot` + `to_external_controller` |
| `from_robot` | `to_neuronavigation` + `to_external_controller` |

The relay does not inspect `data`; it forwards the envelope. Health and camera
frames are broadcast to both peers; everything else follows the table.

## Topics

### Controller → neuronavigation

| Topic | Payload | Meaning |
|---|---|---|
| `External Controller to Neuronavigation: Create Marker` | `{"data": {"position": [mm], "orientation": [deg], "label": str, "marker_type": 3, "is_target": true}}` | create the next coil target |
| `Create marker` | `{"label": "stim_mark"}` | mark the stimulation point right after the pulse |

The extra `{"data": …}` layer on the first topic mirrors what InVesalius'
PubSub expects; `Create marker` is the short topic used for the per-pulse
stimulation mark.

### Neuronavigation → controller

| Topic | Payload | Meaning |
|---|---|---|
| `From Neuronavigation: Coil at target` | markers / pose | the coil reached the target |
| `From Neuronavigation: Coil target created` | markers / pose | realised target after marker creation |

### Neuronavigation → robot

| Topic | Payload | Meaning |
|---|---|---|
| `Neuronavigation to Robot: Set target` | `{"position": [mm], "orientation": [deg]}` | move the coil here |
| `Neuronavigation to Robot: Set objective` | `{"objective": 2}` | move away from the head |
| `Neuronavigation to Robot: Set free drive` | `{"set": bool}` | enable/disable hand-guiding |

### Controller / GUI → robot

| Topic | Payload | Meaning |
|---|---|---|
| `Press robot button` | `{"pressed": bool}` | press the coil against the head |
| `STOP` | `{}` | stop motion now |
| `Pipeline to Robot: Set head mesh` | `{"path": str}` | use this head model for collision |
| `GUI to Robot: set default speed robot` | `{"default_speed_ratio": float}` | travel speed |
| `GUI to Robot: set tuning speed robot` | `{"tuning_speed_ratio": float}` | speed near the head |

### Robot → controller

| Topic | Payload | Meaning |
|---|---|---|
| `Robot to Pipeline: Health status` | `{"robot_id": str, "status": "OK"/"ERROR", "message": str, "info": {…}}` | the robot card on Connections |
| `SIM - Robot to Pipeline: Camera frame` | frame payload | simulated camera stream (simulation only) |

### Robot → neuronavigation

| Topic | Payload | Meaning |
|---|---|---|
| `Robot to Neuronavigation: Send force sensor data` | `{"force_feedback": float}` | the force gate before a pulse |
| `SIM - Robot to Neuronavigation: Tracking State` | `{"position", "orientation", "ik_success", "collision", "motion_done", "tracking_valid", "qpos"}` | simulated tracking (simulation only) |

## Simulation-only topics

The two `SIM -` topics are the virtual twin speaking: the tracking state lets
the simulator drive the neuronavigation without a camera, and the camera frame
feeds the controller's robot view. A real robot never sends them.

## Adding a topic

See [Add a component](extend/components.md). In short: register the constant and
the handler in the robot **and** the nav, handle or send it in the controller,
add it to the production components if it must work with hardware, and update
`tests/test_relay_topics.py` plus this table.

## Failure semantics

- The send path is **fire-and-forget**: when the client is disconnected, the
  message is dropped and nothing raises. A typo or a missing subscription is a
  silent no-op.
- There is no retry and no acknowledgement at the relay level. The state machine
  compensates with timeouts (`COLLECT_TIMEOUT_S`, `EMG_TIMEOUT_S`) and with the
  health loop.
- A lost `Coil at target` is recovered by the operator (**Next**) or by the
  collect timeout; a lost `Health status` turns the card grey/red after a few
  seconds.

## Why the topic strings are fixed

They are the production strings from `tms-robot-control` and InVesalius. Keeping
them byte-identical means the simulator can stand in for the real components,
and a change made here can flow upstream without a translation layer.

## Next

- [Architecture](reference/architecture.md)
- [Add a component](extend/components.md)
- [Troubleshooting](reference/troubleshooting.md)
