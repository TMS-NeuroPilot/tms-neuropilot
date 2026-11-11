# Lab and hardware setup

Nothing on this page is needed for the simulator. It documents how the four
components are wired in the lab and which settings point at which device.

## Network map

The lab network is `192.168.1.0/24`:

| Address | Device | Notes |
|---|---|---|
| `192.168.1.2` | ANT PC (neuronavigation) | InVesalius and the CED/Signal share |
| `192.168.1.3` | NDI camera | optical tracker |
| `192.168.1.5` | Pavian PC | the controller and the relay |
| `192.168.1.10` | Omron cobot | TCP `5890` for movement commands, `502` for Modbus |

The controller talks only to the relay (`RELAY_HOST` / `RELAY_PORT`, default
`127.0.0.1:5000`); every other connection is the relay's business.

!!! warning "Two services must be enabled on the Omron"
    The robot needs the **Modbus Slave** setting and a **TMFlow listen node**,
    otherwise `5890`/`502` are closed and the robot controller reports a health
    error. Enable both before a session; they survive a reboot only if the
    TMFlow project is saved.

## Devices on the control PC

| Device | Default | Setting |
|---|---|---|
| MagVenture stimulator, serial control | `/dev/ttyS1` | `STIMULATOR_PORT` |
| Stimulator TTL trigger | `/dev/parport0` | `STIMULATOR_TTL_PORT` |
| Robot force sensor | `/dev/ttyUSB0` | fixed in `tms-robot-control` |
| NDI tracker ROM files | probe `NT-115`, head `NT-103`, coil `NT-112` | InVesalius |

Your user must be allowed to open the serial and parallel ports:

```bash
sudo usermod -aG dialout,lp $USER      # log out and back in afterwards
ls -l /dev/ttyS1 /dev/parport0
```

If the stimulator is on a USB-serial adapter, the device name is usually
`/dev/ttyUSB0`; set it in **Config › Lab** rather than editing `.env`.

## The EMG computer

The CED 1401 PC shares its Signal data folder over SMB. The controller mounts
it with the credentials from the lab profile:

| Key | Meaning | Default |
|---|---|---|
| `EMG_COMPUTER_IP` | address of the CED PC | `192.168.1.2` |
| `EMG_COMPUTER_USERNAME` | SMB user | `neuro` |
| `EMG_COMPUTER_PASSWORD` | SMB password | `<set in .env>` |

Test the share before a session:

```bash
smbclient //192.168.1.2/<share> -U neuro
```

The exact share name is configured in `tms-robot-control`/the EMG system, not
in NeuroPilot — the controller only reads the files the acquisition writes.

## Software on the other PCs

### Neuronavigation (ANT PC)

InVesalius must run with the remote-control server enabled and pointed at the
same relay:

```bash
python app.py --remote-host http://192.168.1.5:5000
```

The group's InVesalius fork adds the PubSub topics NeuroPilot uses
(`External Controller to Neuronavigation: Create Marker`,
`From Neuronavigation: Coil at target`, …). Stock upstream InVesalius does not
have them; use the fork.

### Robot control (Pavian PC)

```bash
python relay_server.py 5000        # production relay
python main_loop.py                # robot driver
```

Both live in a `tms-robot-control` checkout (the MPI branch for the Omron). If
you set `TMS_ROBOT_CONTROL_PATH` to that checkout, `neuropilot real
--launch-relay` starts `relay_server.py` for you.

!!! danger "Safety — order matters"
    Start the relay, then InVesalius, then `main_loop.py`, then the controller.
    Pressing *Connect to robot* in InVesalius before `main_loop.py` is running
    leaves the robot uninitialised and the first target will not move it.

## Starting a real session

Four terminals on the Pavian PC, in this order:

```bash
# 1. relay (skip if `neuropilot real --launch-relay` starts it)
python relay_server.py 5000

# 2. neuronavigation
python app.py --remote-host http://localhost:5000

# 3. robot
python main_loop.py

# 4. controller
neuropilot real
```

Then, in InVesalius: *Connect to robot*, check the tracking, and confirm the
coil is visible. In the controller, open **Connections** and confirm the three
cards are green before **Start**.

!!! tip "Force sensor says nothing"
    `Awaiting valid pressure data` on the robot side means the force sensor has
    not produced a reading yet. Touch the sensor once with a finger; the stream
    starts and the message disappears.

## What the relay does *not* carry

Images, meshes and EMG files are read from disk, not sent over the relay. The
relay carries poses, topic strings and small status payloads only. A fast
network is therefore nice but not critical; a *reliable* one is, because a lost
message is not retried (see [Relay protocol](reference/relay.md)).

## Next

- [Verify the installation](install/verify.md)
- [Real session checklist](run/real.md)
