# NeuroPilot — design specification

**Version:** 1.1 (2026-11-10) — pending owner approval
**Scope:** merge `cobot-pipeline-controller`, `relay_server_sim`, `tms-robot-sim2`,
`virtual_neuronavigation` into one product-grade repository with one-command startup.

Changes v1.0 → v1.1: no-args launch opens a GUI mode selector; `--headless`
deferred to phase 2 (owner request); §4 clarified.

---

## 1. Goals

1. One repository, one project: the NeuroPilot online TMS mapping suite
   (controller + virtual twin + sim relay).
2. One-command startup: `neuropilot sim` boots the whole simulated stack;
   no manual 4-terminal procedure.
3. One configuration source: ports, paths, and flags in a single module,
   environment-overridable.
4. Zero new runtime dependencies (the supervisor is custom, ~200 lines).

## 2. Non-goals

- No relay-protocol changes: topics stay byte-identical so the real components
  (`tms-robot-control`, Invesalius) keep working unchanged.
- The real robot controller and Invesalius stay separate repositories.
  Real mode optionally *launches* the real relay from a configured
  `tms-robot-control` checkout path (user decision 2026-11-10).

## 3. Target structure

```
neuropilot/                       repo root
  pyproject.toml                  package `neuropilot`, console script `neuropilot`
  .env.example
  README.md
  src/neuropilot/
    __init__.py                   version, tagline
    config.py                     single source of truth (env-overridable)
    cli.py                        argparse entry point
    supervisor.py                 process orchestration
    controller/                   ex cobot-pipeline-controller (package-internal)
    sim_relay/                    ex relay_server_sim
    sim_robot/                    ex tms-robot-sim2 (code + assets/, see 3.1)
    sim_nav/                      ex virtual_neuronavigation
  tests/                          supervisor + config tests; per-component suites later
```

### 3.1 Asset location (deviation from v1.0)

`assets/` lives inside `src/neuropilot/sim_robot/`, not at the repo root:
`sim_robot` computes PROJECT_ROOT from `__file__` and joins relative asset
paths (`assets/mjcf/...`), and the MuJoCo MJCF files resolve sibling mesh
paths relative to the XML location. Keeping assets inside the package
preserves every existing relative reference unchanged. The v1.0 root-level
`assets/` is dropped.

Import rewrites are mechanical: `from config import X` becomes
`from neuropilot.sim_robot import config` style relative imports. Internal
module structure is otherwise untouched — the merge is structural, not a rewrite.

## 4. CLI and startup model

```
neuropilot                           no args → GUI mode selector (simulated vs
                                     real), then launches the chosen stack
neuropilot sim                       full simulated stack (selector skipped)
neuropilot sim --components a,b      subset (debug)
neuropilot controller --sim|--real   controller only, no mode dialog
neuropilot relay                     sim relay only
neuropilot real                      real mode; optional relay launch (see §6)
```

The no-args selector reuses the controller's existing Simulation/Real dialog
design, relocated to the NeuroPilot launcher level (branding: "NeuroPilot").

The controller gets real `--sim` / `--real` CLI flags so its mode is
selectable programmatically — the supervisor starts it in the chosen mode
without any dialog. Today that requires a monkeypatching hack
(`launch_pipeline.py`) because the dialog always runs; with the flags it is
replaced by a supported code path. In the normal flow the controller's own
dialog disappears entirely: the selection happens once, at NeuroPilot level.

Startup order and readiness probes:

1. `sim_relay` — probe: TCP port open (default 5000).
2. `sim_nav` + `sim_robot` — started in parallel; probe: "Connected to relay"
   seen in their output (the reconnect logic added 2026-11-09 makes ordering
   failures non-fatal anyway).
3. `controller` — probe: process alive; started with the mode flag chosen
   above.

Supervisor behavior: role-prefixed log multiplexing to one terminal
(`[robot]`, `[nav]`, `[relay]`, `[controller]`), SIGINT cascade on Ctrl+C,
`--restart-on-crash` optional flag. MuJoCo/GLFW: the supervisor exports the
known `PYGLFW_LIBRARY` path when present on Wayland machines (documented
workaround), configurable in `config.py`. `--headless` (no viewer, for
SSH/CI) is deferred to phase 2.

## 5. Configuration

`src/neuropilot/config.py` — one module, values overridable via environment
or `.env` (loaded once, `python-dotenv`, already a dependency):

- `RELAY_HOST` / `RELAY_PORT` (default `127.0.0.1:5000`)
- `ROOT_FOLDER` (sane local default `~/.neuropilot` or `./results` — replaces
  the cluster-only crash-on-import default; the same pattern used for
  `online_algo` overrides)
- controller keys (health-check flag, MEP window, sampling, …) forwarded to
  the controller package as today
- `TMS_ROBOT_CONTROL_PATH` (optional, for real-relay launch)

## 6. Real mode

`neuropilot real` starts only the controller (with `--real`) after probing
that something listens on `RELAY_PORT`. With
`--launch-relay` (and `TMS_ROBOT_CONTROL_PATH` set), it first starts
`tms-robot-control/relay_server.py` as a child process. The robot controller
and Invesalius remain manual, as documented in the run order.

## 7. Git history and provenance (user decision: fresh)

- Single import commit: "Import controller and virtual-twin components from
  cobot-pipeline-controller / relay_server_sim / tms-robot-sim2 /
  virtual_neuronavigation @ <recorded commit hashes>".
- The four source repos **remain untouched on GitLab** (owner decision
  2026-11-10: no archiving); only their local clones are removed.
- sim2's 479 MB asset-churn history is deliberately not carried over.

## 8. Pre-migration state (resolved)

- sim2 topic rename — committed & pushed 2026-11-10 ✓
- virtual_neuronavigation renames — committed & pushed 2026-11-10 ✓
- controller `__pycache__` churn — excluded via new `.gitignore`
  (`__pycache__/`, `.env`, `results/`, `*.pyc`); not migrated.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Import rewrites break a module | end-to-end `neuropilot sim` gate + topic-trace comparison against the 4-shell run |
| Qt/qasync + SIGINT interplay | supervisor sends SIGINT, controller already closes cleanly on window close; test both |
| Port conflicts on relaunch | supervisor pre-checks the port and offers `--kill-stale` (safe /proc-based kill, per the safe-process-kill skill) |
| Wayland/GLFW viewer failure | env passthrough documented in config; headless mode planned (phase 2) |
| Hidden cwd assumptions (relative asset paths) | grep-audit all four trees for `open(` / relative paths before the move; assets served via package-relative paths |

## 10. Migration order

1. Create GitLab repo `neuropilot` in the group; record the four source hashes.
2. Build the package layout + import rewrites + unified config locally.
3. Implement supervisor + CLI + controller `--sim/--real` flags.
4. Gate: `neuropilot sim` end-to-end run passes (stack behaves like today's
   4-terminal run; marker/target flows produce the same relay traces).
5. Push; archive the four GitLab repos; delete the four local clones;
   update `AGENTS.md` / `doc/knowledge.md`.
6. Phase 2 (optional, later): GUI status panel, Windows notes, real-relay
   polish, test suites per component.
