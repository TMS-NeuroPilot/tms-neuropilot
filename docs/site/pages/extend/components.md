# Add a component

Three kinds of extension share the same rule: **the relay is the contract**.
This page covers a new relay topic, a new process, and the house rules that keep
the suite mergeable with upstream.

## A new relay topic

A topic must be handled on both sides, and the simulators must agree with the
real components.

| Place | What to add |
|---|---|
| `sim_robot/config.py` | a `TOPIC_*` constant (if the robot handles it) |
| `sim_robot/message_handlers.py` | a branch in `handle()` |
| `sim_nav/config.py` / `sim_client.py` | the same for the neuronavigation |
| `controller/pipeline_controller.py` | a handler in `pub_to_func` (incoming) or a `send_message` call (outgoing) |
| `tms-robot-control` | the production handler and its topic constant |
| InVesalius (group fork) | the PubSub subscription |

Payload rules:

- the envelope is `{"topic": str, "data": dict}`; the relay routes by event name
  (`from_robot`, `from_neuronavigation`, `from_external_controller` → `to_*`);
- everything must be JSON-serialisable — convert numpy with `.tolist()`;
- the controller wraps markers in an extra `{"data": …}` layer because
  InVesalius' PubSub does; keep that for compatibility;
- topic names are **unprefixed** descriptive strings
  (`Robot to Pipeline: Health status`), matching upstream's style so changes can
  flow back.

!!! warning "A typo is a silent no-op"
    The send path drops a message when the client is disconnected and never
    raises. A misspelled topic looks exactly like a slow system. That is why
    `tests/test_relay_topics.py` asserts the strings on both sides — add your
    topic to that test.

## A new component process

1. Create a package under `src/neuropilot/<name>/` with `__main__.py`.
2. Register it in `supervisor.py`:

```python
COMPONENTS = {
    ...
    "audit": ("neuropilot.audit", []),
}
```

3. Add it to the sim stack if it belongs there:

```python
def sim_stack(selected=None):
    ...
    specs = {..., "audit": Component("audit", *COMPONENTS["audit"], wait_ready=None)}
```

`wait_ready` is `"port"` (wait for a TCP port), `"line"` (wait for the line
`Connected` in its output) or `None` (no probe). The child runs with its working
directory set to the package directory and `PYTHONUNBUFFERED=1`.

4. Print `Connected` when the component is registered, so the supervisor and the
   operator can see readiness.

!!! note "Why separate processes"
    The controller owns a Qt event loop; the robot owns a MuJoCo viewer; the
    relay owns an aiohttp server. Mixing them in one process produces deadlocks
    that look like hardware faults. One process per role is the design.

## House rules for upstream files

When the change touches code that also exists upstream (`tms-robot-control`,
InVesalius):

- **additive only**: a new function or a new branch, with a comment that says
  *why*;
- removing the addition must restore the original behaviour (± indentation);
- no group-internal `BEGIN`/`END` markers and no group prefix in names;
- do not modify core logic — extend through PubSub where possible;
- trace the behaviour to the **original** caller: many near-identical functions
  exist (`CreateMarker` / `AddMarker` / `_AddMarker`).

The full convention is in the workspace `AGENTS.md` and the project wiki.

## Testing a new topic

```python
# tests/test_relay_topics.py
assert "My new topic" in controller_topics
assert "My new topic" in robot_topics
```

and, for behaviour, a unit test that calls the handler with a realistic
payload:

```python
handlers.handle("My new topic", {"data": {"value": 1}})
assert state.value == 1
```

`tests/test_relay_topics.py` is the readable contract; keep it in sync with
[Relay protocol](reference/relay.md).

## Adding a fit function

1. Add the shape to `controller/fit_functions.py` (`FIT_FUNCTIONS`), mapping a
   display name to the `pynibs.expio.fit_funs` callable.
2. Add the name to the tests in `tests/test_fit_functions.py`.
3. Add a row to the table in [Analysis and fits](results/analysis.md).

The GUI populates its combo from `fit_names()`, so no widget change is needed.

## Next

- [Relay protocol](reference/relay.md)
- [Testing and CI](reference/testing.md)
- [Add a robot](extend/robots.md)
