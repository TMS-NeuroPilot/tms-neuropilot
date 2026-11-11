# Themes and display

Five colour themes ship with the controller. They are not skins: every theme
defines the same token table, and the style sheet, the charts, the 3-D viewport,
the status LEDs, the mode badge and the log bed are all generated from it.

## Switch a theme

**Config › Lab › Theme**. The change applies immediately — no restart — and is
written to `~/.neuropilot/lab.yaml` as `UI_THEME`, so the next session opens
with it.

You can also pin it from `.env`:

```bash
UI_THEME=Graphite
```

`.env` wins over the lab profile, like every other key.

## The five themes

| Theme | Character | Good for |
|---|---|---|
| **Workstation Light** | cool neutral canvas, amber accent | the default; screenshots, daylight |
| **Lab Paper** | warm ivory paper, terracotta accent | bright rooms, figures for a manuscript |
| **Instrument Blue** | cool slate, deep instrumentation blue | keeps amber free to mean "warming up" |
| **Graphite** | dark, neutral two-level charcoal | long sessions in a dim room |
| **Midnight** | dark, blue-black with a cyan accent | next to a bright neuronavigation screen |

The two dark themes are not inverted lights: they define their own status
colours and chart series so a red LED is still red, and the accent still passes
contrast on the dark canvas.

<figure>
  <img src="assets/screenshots/cortical-graphite.png" alt="The Cortical results page in the Graphite dark theme, with the same R² map as the light screenshot.">
  <figcaption>The same map in Graphite. The 3-D view, the scalar bar and the
  cards are recoloured from one token table, so no light panel is left behind.</figcaption>
</figure>

<figure>
  <img src="assets/screenshots/control-graphite.png" alt="The Control page in the Graphite dark theme, including the log bed and the robot view.">
  <figcaption>Control in Graphite: the instrument beds stay dark in every
  theme, and the accent is still legible on the dark canvas.</figcaption>
</figure>

## What a theme controls

Every entry in `controller/theme.py` is a token:

| Group | Tokens |
|---|---|
| text | `ink`, `muted`, `soft`, `mono` |
| surfaces | `canvas`, `card`, `line`, `edge`, `edge_hover`, `hover` |
| accent | `accent`, `accent_dark`, `accent_soft`, `accent_disabled`, `on_accent` |
| disabled | `disabled_bg`, `disabled_edge`, `disabled_ink` |
| status | `ok`, `ok_soft`, `warn`, `danger`, `danger_soft`, `danger_edge` |
| instrument beds | `bed`, `bed_ink`, `bed_muted`, `bed_sel` |
| misc | `scroll`, `scroll_hover`, `led_off`, `grid` |
| charts | `series` (six colours) |

The style sheet is built from these; `MeshWidget.apply_theme`,
`MplGraphWidget.apply_theme` and the LED renderer use the same table. That is
why changing the theme does not leave a light-coloured plot on a dark window.

## Contrast is enforced

`tests/test_theme.py` computes WCAG contrast ratios from the tokens:

- body text on card and canvas **≥ 7:1**,
- captions (`muted`) and status colours **≥ 4.5:1**,
- white text on the accent **≥ 4.5:1** (or the theme must set `on_accent` to a
  dark colour, which the dark themes do).

A theme that fails these numbers fails CI. If you add a theme, run:

```bash
pytest tests/test_theme.py -q
```

## UI scale

The window is laid out for 1244×960 and scales with the screen. Force a scale
when the automatic choice is wrong:

```bash
NEUROPILOT_UI_SCALE=1.25       # in .env
```

| Value | Effect |
|---|---|
| unset | scale from the screen's DPI |
| `1.0` | design size |
| `1.25`, `1.5`, … | larger fonts and controls |
| below `1.0` | clamped to `1.0`; shrinking breaks the card layouts |

The UI scale is applied at start; changing it needs a restart.

## Display details

| Element | Behaviour |
|---|---|
| **Tab strip** | follows the theme's card colour, including the LED corner |
| **Log bed** | dark instrument surface in every theme, for readability |
| **Robot view** | dark bed; the MuJoCo scene is rendered by VTK with its own lighting |
| **Charts** | series palette from the theme, grid from `grid` |
| **3-D scalar bar** | recoloured with the theme's ink and card colours |
| **Screenshots** | the exported PNG includes the corner overlays and the current theme |

## Accessibility

- The theme names are plain descriptions, not brand names; the combo is
  keyboard-navigable.
- Every status is text (`OK`, `ERROR`) as well as colour, so a colour-blind
  operator does not lose information.
- The contrast tests above are the objective floor; they do not replace a check
  on the actual monitor in the lab.

## Add your own

[Add a theme](extend/themes.md) documents the token table and the test contract
a new theme must satisfy.

## Next

- [Add a theme](extend/themes.md)
- [Config page](gui/config.md)
