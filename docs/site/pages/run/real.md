# Real session checklist

This is the operational page. It assumes the installation, the subject data and
the lab wiring are done; the goal is that nothing about the software is decided
for the first time while a subject is in the chair.

!!! danger "Safety — research software, not a medical device"
    NeuroPilot has no medical approval. Real stimulation requires ethics
    approval, a trained operator, the stimulator's own safety limits and written
    consent. This checklist covers the software, not the medical procedure.

## The day before

- [ ] Ethics approval and consent form are on file for this protocol.
- [ ] The subject's data are pseudonymised; the project name carries no name or
      date of birth.
- [ ] Head mesh, ROI, E-field library, placements and order file exist for this
      subject and pass the [sanity checks](prepare/subject-data.md).
- [ ] The target-order file was reviewed by the person who owns the protocol.
- [ ] A study profile is saved with the intended fit function, ISI, amplitude
      and MEP windows.
- [ ] `ROOT_FOLDER` has free space for the session and is writable.
- [ ] The E-field mode is decided: precomputed (library ready) or online
      (solver loads in about a minute).

## One hour before

- [ ] Relay running: `python relay_server.py 5000`.
- [ ] InVesalius running with `--remote-host http://localhost:5000`.
- [ ] Robot driver running: `python main_loop.py`.
- [ ] Controller running: `neuropilot real`.
- [ ] **Connections** page: stimulator, EMG and robot all green.
- [ ] **Project** page: the project loads without an error dialog.
- [ ] **Cortical results**: the mesh is displayed and the coil model is loaded.
- [ ] Stimulator armed and the amplitude shows the value you expect.
- [ ] EMG: tapping the electrode produces a visible trace on **MEP results**.
- [ ] Coil cooling is on; the coil is at room temperature.
- [ ] The robot's force sensor shows a reading (touch it once if the robot side
      says `Awaiting valid pressure data`).

## Five minutes before

- [ ] Subject seated, head supported, coil cable routed with slack.
- [ ] Neuronavigation registration accepted; the coil is tracked at the first
      target.
- [ ] Emergency stop within reach of the operator.
- [ ] **Control** page: E-field mode selected, Start enabled.
- [ ] Amplitude, repetitions, minimum interval and pulse shape match the
      protocol.
- [ ] Stop criteria are written down and visible (see below).

## During the session

- Watch the **Control** log, not only the 3-D view.
- A pulse is only fired when the coil is at target, the force is above the
  threshold and the minimum interval has elapsed.
- If a system drops out, the loop holds:
  `Held at <step>: <system> not ready. Finish ends the session.`
  Fix it, press **Reconnect**, and the loop continues.
- **Pause** holds before the next pulse; the coil stays on the head.
- **Next** skips a target, **Back** repeats the previous one. A pulse in flight
  cannot be taken back (`Previous ignored: a pulse is in flight.`).

!!! danger "Safety — stop conditions"
    Stop the session with **Move Coil Up** and then **Finish** if the subject
    reports discomfort, the coil overheats, the robot faults, the subject moves
    out of tracking, or the MEPs disappear without an explanation. The software
    cannot decide this for you.

## Ending

1. Press **Finish**. The controller finishes the current step, retracts the
   robot and waits for the last analysis.
2. Wait for `We are done.` in the log.
3. Confirm the results CSV exists and is not empty (path shown on the Project
   page under *Results file*).
4. Export the R² table and the placement log from **Cortical results** if the
   analysis needs them: **Export CSV…**.
5. Stop the controller, then `main_loop.py`, then InVesalius, then the relay.

## After the session

- [ ] Results CSV copied to the study folder and backed up.
- [ ] R² export and placement log copied next to it.
- [ ] The E-field library used for the session archived with the results.
- [ ] The session notes record amplitude, coil, E-field mode, pulse count and
      any skipped targets.
- [ ] The subject's data folder is checked for accidental identifiers.

## If something goes wrong

| Situation | Immediate action |
|---|---|
| Robot does not move | Check the robot card and `main_loop.py`; press **Reconnect** |
| Coil never reaches the target | **Next** to skip; check tracking and the placement reach |
| Stimulator does not fire | Check the stimulator card and the serial port; **Finish** if it persists |
| EMG traces are flat | Check the amplifier and the share; the session can continue but the MEPs are lost |
| Controller freezes | Kill and restart the controller; the results of completed pulses are in the CSV |
| Wrong project loaded | Stop the run, reload the project, restart the mapping |

See [Troubleshooting](reference/troubleshooting.md) for the full table.

## Next

- [Manual mode](run/manual.md) — the same session without a robot.
- [Export and data formats](results/export.md) — what the session leaves behind.
