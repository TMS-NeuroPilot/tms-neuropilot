# Hardware setup

Nothing on this page is needed for the simulator. It explains how to connect
*your* hardware to TMS NeuroPilot: which pieces exist, which endpoints TMS NeuroPilot
needs, and how to check each one before a subject arrives.

The suite does not assume a particular lab. One PC can host everything, or each
piece can live on its own machine; what matters is that the relay is reachable
from every peer and that the settings below point at the right devices. The
figure shows one complete setup; your lab will differ in detail, and
[the trigger example](#an-example-one-trigger-two-consumers) at the end of
section 7 states what the wiring has to guarantee.

<figure>
  <img src="assets/diagrams/hardware-setup.png" alt="Example wiring of a real session: TMS NeuroPilot, robot control, InVesalius and the relay inside a dashed one-or-multiple-machines frame; below them the stimulator, the EMG recording and the robot, with the LAN, the camera and the serial, parallel-trigger and trigger-out lines.">
  <figcaption>One wiring of a real session, not the only one. The relay topics
  run over IP, so the controller, the robot control and InVesalius may share a
  machine or sit on separate ones. The stimulator is controlled over serial and
  triggered over a parallel line whose T-split also starts the EMG acquisition;
  the stimulator's trigger output marks the delivered pulse in the
  neuronavigation; the EMG acquisition writes one sweep file per pulse to a
  share that the controller reads. The devices are examples: any arm with a
  driver, any stimulator with a serial interface, any acquisition system that
  writes a share.</figcaption>
</figure>

## The pieces

| Role | What runs there | What TMS NeuroPilot needs from it |
|---|---|---|
| **Control PC** | controller + relay | a display, the `neuropilot` environment, a writable data folder |
| **Neuronavigation PC** | InVesalius (group fork) | `--remote-host` pointed at the relay; the coil tracked |
| **Robot controller** | `tms-robot-control` | the driver for your arm; a working force sensor |
| **Stimulator** | your stimulator + its driver (`magicpy` for MagVenture) | a serial port and a TTL line on the control PC |
| **EMG acquisition** | acquisition software writing to a share (CED/Signal is one example) | an SMB share the control PC can read |

The relay is the only network service TMS NeuroPilot itself requires. Everything
else is either a local device or a file share.

## 1. Write down your addresses

Fill this in before touching a configuration file; every value has a home in
`.env` or the lab profile.

| Item | Example | Your value |
|---|---|---|
| Relay host | `relay.lab.example` (or `192.0.2.10`) | |
| Relay port | `5000` | |
| Controller PC | the machine with the display | |
| Neuronavigation PC | `nav.lab.example` | |
| Robot controller | same PC as the relay, or another | |
| Stimulator serial device | `/dev/ttyUSB0` | |
| Stimulator TTL device | `/dev/parport0` | |
| EMG PC address | `192.0.2.20` | |
| EMG SMB user / password | a dedicated account | |
| Data folder | `/data/neuropilot` | |

`192.0.2.0/24` is the documentation range; replace the examples with your
addresses. Avoid reusing the defaults (`127.0.0.1`, `192.168.1.2`) unless they
really are your machines.

## 2. Network

- Put the control PC, the neuronavigation PC and the robot controller on the
  same network, or on networks that can reach each other.
- Give the relay host a **stable address** (static or DNS), not a DHCP lease
  that changes between sessions.
- Allow inbound **TCP 5000** (or your `RELAY_PORT`) on the relay host, and
  outbound connections from every peer.
- Allow **TCP 445** from the control PC to the EMG PC for the SMB share.
- Keep the clocks synchronised (NTP). The results CSV and the logs use
  timestamps from different machines.

Check reachability from each peer before a session:

```bash
nc -vz relay.lab.example 5000
smbclient -L //192.0.2.20 -U <user>
```

## 3. Control PC

```bash
conda activate neuropilot
cp .env.example .env
```

Set at least:

```bash
RELAY_HOST=relay.lab.example     # or 127.0.0.1 when the relay runs here
RELAY_PORT=5000
ROOT_FOLDER=/data/neuropilot
```

The relay is `relay_server.py` from `tms-robot-control`; with

```bash
TMS_ROBOT_CONTROL_PATH=/opt/tms-robot-control
```

`neuropilot robo` starts and manages it automatically when the checkout is
configured; the Relay card on Connections can start or restart it. For a dry
run without hardware, `neuropilot relay` starts the simulated relay instead.

## 4. Neuronavigation PC

Use the group's InVesalius build: it adds the PubSub topics TMS NeuroPilot relies on
(`External Controller to Neuronavigation: Create Marker`,
`From Neuronavigation: Coil at target`, …). Stock upstream InVesalius does not
have them.

Start it pointed at the relay:

```bash
python app.py --remote-host http://relay.lab.example:5000
```

On that PC:

1. Configure the optical tracker and load the ROM files for your probe, head
   reference and coil.
2. Run the registration and accept it.
3. Confirm the coil is tracked and visible in the 3-D view.
4. If the neuronavigation timestamps the delivered pulse, check that input. In
   the reference setup the stimulator's trigger output is routed to this PC, and
   the navigation records the coil pose at the pulse.

The controller creates a marker per target and waits for *Coil at target*; it
never talks to the camera directly.

## 5. Robot controller

`tms-robot-control` contains the relay server and the robot driver. Install the
driver for **your** arm, and enable whatever remote interface it needs. For
example, an Omron arm needs its Modbus slave and a TMFlow listen node enabled;
other vendors have their own equivalent. The robot's manual is the authority
here, not this page.

Before the first session:

- **Tool point** — the driver's tool centre point must be the coil's
  stimulation point, not the flange or the handle. Re-measure it if the coil
  mount changed.
- **Force sensor** — the driver must publish a force reading; TMS NeuroPilot uses
  it as the contact gate before a pulse.
- **Reach and collisions** — teach the approach pose and verify that the first
  target is reachable without self-collision.
- **Speeds** — the controller sends the default and tuning speeds at Start;
  confirm they are the values you expect.

```bash
python main_loop.py        # after the relay; then Connect to robot
```

In InVesalius, press *Connect to robot* only after `main_loop.py` is running.

!!! danger "Safety: order matters"
    Start the relay, then InVesalius, then the robot driver, then the
    controller — and press *Connect to robot* in InVesalius only after the
    driver is running. TMS NeuroPilot can start the relay and InVesalius for you,
    but `main_loop.py` must already be running before you connect in
    InVesalius. Connecting to a robot whose driver is not running leaves it
    uninitialised and the first target will not move it.

## 6. Stimulator

The stimulator is driven over a serial port and triggered over a TTL line, both
on the control PC. The shipped driver, `magicpy`, targets MagVenture; another
stimulator needs its own driver behind the same interface.

```bash
sudo usermod -aG dialout,lp "$USER"    # log out and back in afterwards
ls -l /dev/ttyUSB0 /dev/parport0
```

If the controller prints `Permission denied` for the serial device, the
group change has not reached the process yet. Log out and back in for the GUI,
or run `newgrp dialout` in the terminal that starts TMS NeuroPilot. The controller
prints this fix in the terminal when it sees the error. If `/dev/parport0` is
missing, the controller continues with the serial port only; load the parallel
driver with `sudo modprobe ppdev` and check the `lp` group only if you actually
use the TTL line.

Set the devices in **Config › Lab** (or `STIMULATOR_PORT` /
`STIMULATOR_TTL_PORT` in `.env`). USB-serial adapters usually appear as
`/dev/ttyUSB0`; the parallel port may be `/dev/parport0` or a different device
depending on the card. If the same trigger must also start the EMG acquisition,
the stimulator has to delay the pulse after the trigger input; in the reference
setup this delay is 0.5 s (see
[the trigger example](#an-example-one-trigger-two-consumers)). Use the stable `/dev/serial/by-id/...` path if the
adapter enumerates differently across reboots.

!!! danger "Safety: test pulses"
    Test the stimulator with the coil away from people and according to your
    local rules. Check the displayed amplitude on the device itself before the
    first pulse of a session; the GUI value is not a substitute.

## 7. EMG acquisition

The EMG acquisition PC writes its files to a folder it shares over SMB (CED /
Signal in the reference setup). The controller reads those files; it does not
record EMG itself.

| Setting | Meaning | Default |
|---|---|---|
| `EMG_COMPUTER_IP` | address of the EMG PC | `192.168.1.2` |
| `EMG_COMPUTER_USERNAME` | SMB user | `neuro` |
| `EMG_COMPUTER_PASSWORD` | SMB password | `<set in .env>` |
| `EMG_CONNECT_TIMEOUT_S` | initial SMB connection timeout | `3` |

The share name is fixed in the acquisition setup, not in TMS NeuroPilot. Confirm
that the control PC can list it, and that new files appear there when you tap
the electrodes:

```bash
smbclient //192.0.2.20/<share> -U <user>
```

### An example: one trigger, two consumers

The reference setup in the MPI lab solves the timing problem like this; any
arrangement with the same properties works.

1. The controller sends the fire command over the serial line (intensity, pulse
   shape) and a TTL on the parallel port.
2. The TTL is split: one branch goes to the stimulator's trigger input, the
   other to the trigger input of the EMG acquisition (CED 1401).
3. The stimulator is set to wait **0.5 s** after it receives the trigger before
   it delivers the pulse. That delay is the head start of the EMG: the
   acquisition is already running when the pulse arrives, so the sweep contains
   the pre-activation window and the response.
4. The stimulator's trigger output is a second TTL, sent when the pulse is
   actually delivered. It is routed to the neuronavigation, which records the
   coil pose of that pulse; this is the pose the E-field is computed for.
5. The acquisition software (Signal, on the CED) runs a script that records the
   sweep and writes one text file per pulse into a folder on the EMG PC.
6. TMS NeuroPilot reads the newest file from that folder over SMB after the pulse
   and reduces it to a peak-to-peak MEP and the pre-activation measures.

What matters is not this particular wiring but its properties: a TTL that starts
the acquisition before the pulse, a pulse confirmation that the neuronavigation
can timestamp, and a per-pulse sweep that the controller can read without asking
the acquisition PC. A different amplifier or a different delay works as long as
those three exist; the MEP windows and the sampling rate then follow from your
own hardware (see [EMG channels and MEP windows](prepare/emg.md)).

Then set `EMG_CHANNELS`, `SAMPLING_RATE` and the MEP window for your amplifier
(see [EMG channels and MEP windows](prepare/emg.md)).

## 8. Start everything

On the control PC (or the machines that host each role), in this order:

```bash
# 1. relay
python relay_server.py 5000

# 2. neuronavigation
python app.py --remote-host http://relay.lab.example:5000

# 3. robot driver
python main_loop.py

# 4. controller
neuropilot robo
```

Then:

1. In InVesalius: *Connect to robot*, verify tracking, confirm the coil.
2. In the controller: **Connections** — the stimulator, EMG and robot cards must
   be green; **Project** — the subject is loaded; **Control** — the E-field mode
   is selected and Start is enabled.

## 9. Verify each system

| Check | Where |
|---|---|
| relay reachable from every peer | `nc -vz <relay> 5000` |
| stimulator answers on its port | **Connections › Stimulator** details |
| EMG share readable | **Connections › EMG**, or `smbclient` |
| robot health and force sensor | **Connections › Robot** details |
| InVesalius creates a marker | press Start; the marker appears |
| coil reaches the target | the robot moves and *Coil at target* arrives |
| a test pulse produces an MEP | **MEP results** after one pulse |

`Awaiting valid pressure data` on the robot side means the force sensor has not
produced a reading yet: touch it once and the stream starts.

## Example configuration

A minimal `.env` for a lab where the relay and controller run on the same PC
and the other pieces are remote:

```bash
RELAY_HOST=127.0.0.1
RELAY_PORT=5000
ROOT_FOLDER=/data/neuropilot
STIMULATOR_PORT=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10K...-if00-port0
STIMULATOR_TTL_PORT=/dev/parport0
EMG_COMPUTER_IP=192.0.2.20
EMG_COMPUTER_USERNAME=emg
EMG_COMPUTER_PASSWORD=change-me
EMG_CHANNELS=FDI,APB,ADM
SAMPLING_RATE=4000
CUTOFF_FREQ=500
TMS_PULSE_TIME=5
START_MEP=10
END_MEP=100
ONLINE_FEM_SOLVER=pardiso
ONLINE_FEM_ANISOTROPY=scalar
```

The same values can be set in **Config › Lab** and then live in
`~/.neuropilot/lab.yaml`; `.env` pins a value and wins over the profile (see
[Settings model](config/model.md)).

## Migrating an existing installation

- Keep the old `.env` and compare it with `.env.example`; the keys are
  documented in the [`.env` reference](config/env.md).
- Move the hardware values you want to edit in the GUI into `lab.yaml`
  (**Config › Lab › Save lab profile**), and leave the bootstrap keys in
  `.env`.
- If a value refuses to change, it is still pinned in `.env` or exported in the
  shell; the status line on Config › Lab counts those overrides.

## What the relay does *not* carry

Images, meshes and EMG files are read from disk, not sent over the relay. The
relay carries poses, topic strings and small status payloads only. A fast
network is nice; a *reliable* one matters, because a lost message is not
retried (see [Relay protocol](reference/relay.md)).

## Next

- [Verify the installation](install/verify.md)
- [Real session checklist](run/real.md)
- [Troubleshooting](reference/troubleshooting.md)
