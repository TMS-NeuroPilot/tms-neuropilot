# E-field modes

Every pulse needs an E-field. NeuroPilot can get it two ways, and the mode can
change during a session without breaking the regression.

<figure>
  <img src="assets/diagrams/efield-modes.svg" alt="The precomputed and online E-field paths, both ending in one per-pulse row appended to the regression.">
  <figcaption>Two sources, one row format. The mode decides where the row comes
  from; the analysis does not care.</figcaption>
</figure>

## Precomputed

The field for every placement was solved before the session
([E-field library](prepare/efield-library.md)). At pulse time the controller
looks up the row of the *planned* placement:

```text
e_matrix[target_index]  →  one row of E_mag  →  regression
```

- Ready immediately.
- Requires `e_field_path` and `targets_file` in the project.
- The coil must actually be at the planned placement for the row to be true;
  the controller flags a large aim error in the log and in the export.
- The CSV records `e_field_mode = precomputed` for those pulses.

## Online

The field is solved for the realised coil pose while the session runs, using
SimNIBS through `OnlineFEMManager`:

```text
realised pose  →  OnlineFEMManager  →  one field vector  →  regression
```

- The solver loads once at the start: about **one minute**.
- Needs the `.msh` head mesh, the ROI surface and the coil model.
- Does **not** need the E-field library or the placements library, though a
  target-order file still helps.
- Solver settings come from **Config › Lab › E-field solver**:

| Setting | Values | Default |
|---|---|---|
| Solver | `pardiso` (fast) or `amg` (robust, slower) | `pardiso` |
| Anisotropy | `scalar` or `vector` (needs a DTI tensor in the mesh) | `scalar` |

- The CSV records `e_field_mode = online` for those pulses.

## The hint under the radios

The one line below the E-field buttons is the mode's state machine:

| Text | Meaning |
|---|---|
| `Choose a mode to enable Start.` | no mode selected; Start is disabled |
| `Precomputed library — ready immediately.` | precomputed mode with a library loaded |
| `Warming up the online solver (about a minute) — pulses wait until it is ready.` | online mode, solver loading |
| `Online solver ready.` | online mode, solving per pulse |
| `Online solver unavailable — switch to Precomputed.` | SimNIBS/petsc4py not importable |

## Switching mid-run

The mode is not locked during a session. Every pulse stores the field it was
stimulated with, so switching only affects the following pulses:

1. The regression matrix is assembled from the per-pulse rows
   (`pulse_e_fields`), not from the library directly.
2. A pulse with a missing field is dropped, and the MEP history is re-indexed
   with it, so the remaining rows stay aligned.
3. The export records the source per pulse (`e_field_mode`), which makes a mixed
   session auditable.

What happens on a switch:

- **Precomputed → Online:** the solver starts loading. The coil stays on target
  and the pulse is **held** until the solver is ready; the log says
  `Online solver ready, stimulation resumes.` Switching back releases the pulse
  immediately.
- **Online → Precomputed:** immediate; no solver state is needed.

!!! warning "Warm the solver before the subject is positioned"
    The first switch to online costs about a minute during which no pulse can
    fire. Do it during setup, not between two targets with the coil on the head.

## Which mode to use

| Situation | Recommendation |
|---|---|
| Library exists and the coil reliably reaches the planned pose | precomputed |
| No library yet, or the head moved since it was computed | online |
| Many pulses, session time is tight | precomputed |
| The interesting question is the field of the *realised* pose | online |
| Debugging the stimulator/EMG only | either; precomputed is faster to start |

## What the analysis sees

Both modes produce the same structure:

```python
pulse_e_fields = [row_0, row_1, row_2, ...]   # one vector per pulse
pulse_modes    = ["precomputed", "online", ...]
```

`assemble_analysis_matrix()` drops the `None` rows and returns the indices it
kept, which is why an aborted pulse never shifts the MEP history.

## The project file remembers

`efield_mode` is written into the project YAML, so a subject resumed later opens
in the same mode. It is one of the few live controls that travel with the
subject; the amplitude and repetitions do too.

## Next

- [The mapping loop](run/mapping-loop.md)
- [Analysis and fits](results/analysis.md)
