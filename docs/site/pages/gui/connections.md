# Connections page

The **Connections** page is the health dashboard: one card per system, a status
LED, the last message, the connection details and a **Reconnect** button. Start
is gated on this page being green.

<figure>
  <img src="assets/screenshots/connections-sim.png" alt="The Connections page in simulation mode with the stimulator, EMG and robot cards green.">
  <figcaption>Three cards in simulation. Each shows the status, the last
  message and the connection details the system publishes.</figcaption>
</figure>

## The cards

| Card | Backend (simulation) | Backend (real) |
|---|---|---|
| **Stimulator** | virtual stimulator | your stimulator via `magicpy` on `STIMULATOR_PORT` |
| **EMG** | virtual EMG computer | your EMG PC's share (`EMG_COMPUTER_IP`) |
| **Robot** | virtual MuJoCo robot | `tms-robot-control` over the relay |

In manual and training modes the robot card is absent. In training the
stimulator card is real and the EMG card is the virtual EMG.

## What a card shows

| Field | Meaning |
|---|---|
| **Status** | `—` (unknown), `OK`, or `ERROR`, with the LED colour |
| **Message** | the last status message, e.g. `No Connection` |
| **Last update** | when the last health packet arrived |
| **Details** | up to five label/value rows published by the system |
| **Reconnect** | enabled when a recovery is available for the current error |

### Detail rows you will see

| System | Details |
|---|---|
| Stimulator | port, TTL port, connected, model, serial number, coil type, waveform, temperature |
| EMG | transport (`SMB2`), host, share, user, channel names and count |
| Robot | relay URL, robot ID, model/firmware from the robot's `info{}`, link state |

The rows are populated in the order the system publishes them; unused rows are
hidden, so a system with two details does not leave three empty lines.

## LED states

| LED | Status | Operator action |
|---|---|---|
| grey | `—` / `Not Initialized` | wait a second; press **Reconnect** |
| green | `OK` | none |
| red | `ERROR` | read the message; press **Reconnect**; check the hardware |

The health loop runs at about 1 Hz. A card can lag a second behind reality; the
*Last update* field tells you how stale it is.

## The Start gate

Start is enabled only when:

- the **robot** is ready (or the session is in manual or training mode),
- the **stimulator** is ready,
- the **EMG** is ready,
- the **E-field mode** has what it needs (library loaded, or online solver ready).

The hint under the E-field radios names the missing piece when Start is grey.

## Recovery

**Reconnect** runs the system's own recovery path: it re-opens the serial port,
re-mounts the share, or re-sends the robot handshake. It does not restart the
stack and it does not interrupt a running mapping — the loop holds while the
system is down and continues when it recovers.

If the button is disabled, the system reports no software recovery for its
current error; the message says what failed and the fix is on the hardware side
(cable, power, network, robot mode).

## Real mode order

1. Relay.
2. InVesalius (with the remote-control server).
3. `main_loop.py`.
4. The controller.

If the robot card is red with a connection message, check that `main_loop.py` is
running and that the robot's Modbus/listen services are enabled. See
[Hardware setup](install/hardware.md).

## Training order

1. Relay.
2. InVesalius (with the remote-control server).
3. `neuropilot training`.

No robot driver and no EMG PC are needed. The stimulator card is the real
device; the EMG card is the E-field-driven virtual EMG.

!!! tip "Force sensor"
    `Awaiting valid pressure data` comes from the robot side when the force
    sensor has not produced a reading. Touch the sensor once; the stream starts.

## Simulation

In simulation all three cards go green immediately and the details show the
virtual devices (the simulated stimulator model, the virtual EMG channels, the
MuJoCo robot). A red card in simulation means a component failed to start —
check the terminal for the component's log prefix.

## Next

- [Control page](gui/control.md)
- [Troubleshooting](reference/troubleshooting.md)
