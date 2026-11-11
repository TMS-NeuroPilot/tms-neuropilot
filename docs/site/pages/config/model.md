# Settings model

Settings live in four layers. This page states which one wins, which file to
edit for a given change, and what needs a restart.

<figure>
  <img src="assets/diagrams/config-precedence.svg" alt="Configuration precedence: shell environment above .env above lab.yaml above built-in defaults, with the study profile and project file applied to the session.">
  <figcaption>Four layers decide a running value. The study profile and the
  project file are session data applied to the controls, not extra layers.</figcaption>
</figure>

## The chain

```text
shell environment  >  .env (repository root)  >  ~/.neuropilot/lab.yaml  >  built-in defaults
```

1. **Shell environment** — anything exported before the process starts. Highest
   priority; useful for one-off runs:
   `RELAY_PORT=5100 neuropilot sim`.
2. **`.env`** — the repository-root bootstrap file. It is loaded once by
   `neuropilot.config` before any component imports, and it can pin *any* lab
   key, which is why an existing installation keeps behaving as before.
3. **Lab profile** — `~/.neuropilot/lab.yaml`, edited in **Config › Lab**
   (`NEUROPILOT_LAB_FILE` moves it). It is exported with `os.environ.setdefault`,
   so it only fills keys the shell and `.env` left unset.
4. **Built-in defaults** — the values in `lab_profile.DEFAULTS` and the `_env()`
   calls in `neuropilot/config.py`.

## The two session layers

The **study profile** and the **project file** are not overrides of the chain.
They are data that the GUI applies to the live controls:

| Layer | Edited in | Applies |
|---|---|---|
| study profile | Config › Study | on **Apply to session**; MEP windows and channel names on restart |
| project file | Project page | on **Load** |

A value that `.env` pins is still the value after a restart, even if a study
profile set something else at runtime.

## Which file should I edit?

Ask one question:

| Question | Scope | Where |
|---|---|---|
| Would another lab need a different value? | **Lab** | `lab.yaml` (Config › Lab) |
| Would another study need a different value? | **Study** | study YAML (Config › Study) |
| Would another subject need a different value? | **Subject** | project YAML |
| Must the value exist before the GUI starts? | **bootstrap** | `.env` |

Examples:

- relay address, serial ports, EMG credentials, theme → Lab
- fit function, ISI, amplitude, MEP windows, channel names → Study
- mesh, ROI, library, placements, results path → Subject
- data folder, readiness timeout, GLFW library, "run the GUI at all" → `.env`

## What needs a restart

| Change | Restart? | Why |
|---|---|---|
| any `.env` value | **yes** | `.env` is read once at import |
| lab relay, data folder, UI scale | **yes** | read at start |
| lab robot model | **yes** | the simulator builds the scene at start |
| lab solver/anisotropy | no | read when the online solver loads |
| lab stimulator/EMG ports | yes | read when the systems connect |
| theme | **no** | applied live and saved |
| study mapping/stimulation values | no | **Apply to session** |
| study MEP windows, channel names | **yes** | read at import by the controller |

## Overrides are visible

Config › Lab marks a field that `.env` pins (tooltip) and counts them in the
status line:

```text
Loaded lab.yaml (~/.neuropilot/lab.yaml) · 3 key(s) overridden by .env
```

If a value you just typed does not survive a restart, this line is the reason.

## Why `.env` stays the top file

Two practical reasons:

- **Bootstrap keys** must be readable before the GUI exists: `ROOT_FOLDER`,
  `RELAY_PORT`, `READINESS_TIMEOUT_S`, `PYGLFW_LIBRARY`,
  `ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL`.
- **Pinning** lets a lab freeze a value without granting edit rights to
  `~/.neuropilot/lab.yaml`, and lets CI override everything from the
  environment.

## The lab profile is portable

`lab.yaml` contains only the keys in `LAB_KEYS` and is written with a header
that restates the precedence. Unknown keys are preserved when the GUI writes the
file, so hand-written comments and extra keys survive an edit.

## Where each file lives

| File | Path | Moved by |
|---|---|---|
| bootstrap | `<repo>/.env` | `NEUROPILOT_ENV_FILE` (the Config tab's editor; tests/CI) |
| lab profile | `~/.neuropilot/lab.yaml` | `NEUROPILOT_LAB_FILE` |
| study profile | `<ROOT_FOLDER>/study.yaml` by default | any path on save/load |
| project | wherever you save it | — |
| session cache | `~/.neuropilot/last_session.yaml` | — |

## Next

- [`.env` reference](config/env.md) — every key with its default.
- [Lab profile reference](config/lab.md) — the `lab.yaml` keys.
- [Troubleshooting](reference/troubleshooting.md) — when a value will not stick.
