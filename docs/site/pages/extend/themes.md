# Add a theme

A theme is one dictionary of tokens in `controller/theme.py`. Everything else —
the Qt style sheet, the charts, the 3-D viewport, the LEDs, the log bed — is
generated from it.

## 1. Copy an existing theme

Pick the theme closest to what you want and copy its block in `THEMES`:

```python
THEMES = {
    ...
    "My Lab": {
        "ink": "#1B1F24", "muted": "#5A636E", "soft": "#3C444D", "mono": "#38434E",
        "canvas": "#F4F5F7", "card": "#FFFFFF", "line": "#E2E5E9",
        "edge": "#D9DDE3", "edge_hover": "#C6CCD4", "hover": "#EEF0F2",
        "accent": "#B45309", "accent_dark": "#92400E", "accent_soft": "#FDF3E7",
        "accent_disabled": "#E3C6A2", "on_accent": "#FFFFFF",
        "disabled_bg": "#F1F3F5", "disabled_edge": "#E7EAEE", "disabled_ink": "#A9B4BE",
        "ok": "#15803D", "ok_soft": "#E8F5EC", "warn": "#A16207",
        "danger": "#B91C1C", "danger_soft": "#FDF3F3", "danger_edge": "#EBC4C4",
        "bed": "#12151A", "bed_ink": "#C9D4DE", "bed_muted": "#7C8794",
        "bed_sel": "#2A333B",
        "scroll": "#C6CCD4", "scroll_hover": "#AEB6C0",
        "led_off": "#C9CFD6", "grid": "#E4E7EB",
        "series": ["#1D4ED8", "#C2410C", "#15803D", "#7E22CE", "#0F766E", "#BE185D"],
    },
}
```

## 2. The token contract

Every theme must define every token. `tests/test_theme.py` iterates the table and
fails on a missing key, so a typo is a test failure, not a black widget.

| Group | Tokens |
|---|---|
| text | `ink`, `muted`, `soft`, `mono` |
| surfaces | `canvas`, `card`, `line`, `edge`, `edge_hover`, `hover` |
| accent | `accent`, `accent_dark`, `accent_soft`, `accent_disabled`, `on_accent` |
| disabled | `disabled_bg`, `disabled_edge`, `disabled_ink` |
| status | `ok`, `ok_soft`, `warn`, `danger`, `danger_soft`, `danger_edge` |
| instrument beds | `bed`, `bed_ink`, `bed_muted`, `bed_sel` |
| misc | `scroll`, `scroll_hover`, `led_off`, `grid` |
| charts | `series` (exactly six colours) |

## 3. Satisfy the contrast tests

```bash
pytest tests/test_theme.py -q
```

The tests compute WCAG ratios:

| Pair | Minimum |
|---|---|
| `ink` on `card` | 7:1 |
| `ink` on `canvas` | 7:1 |
| `muted` on `card` | 4.5:1 |
| status colours on `card` | 4.5:1 |
| `on_accent` on `accent` | 4.5:1 |

`ok`, `warn`, `danger` are also used as **text**, so they must pass as text, not
only as a fill. If your accent is bright, set `on_accent` to a dark ink (that is
what Graphite and Midnight do).

## 4. Pick the mode

`is_dark(name)` is computed from the luminance of `canvas`. It decides which
`on_accent` default and which chart treatment is appropriate; it is not a manual
flag.

## 5. Use it

**Config › Lab › Theme** lists the new name automatically (the combo is
populated from `THEMES`), and `UI_THEME=My Lab` works from `.env`. The choice is
written to the lab profile when changed in the GUI.

## 6. Check the parts a style sheet cannot reach

The theme is applied to more than the window. Open a session and check:

- [ ] status LEDs (green/red/grey) on Connections,
- [ ] the mode badge on Config › Lab,
- [ ] the log bed on Control,
- [ ] the MEP trend and the EMG trace (series colours and grid),
- [ ] the 3-D scalar bar and the placement spheres,
- [ ] the tab strip and its LED corner,
- [ ] disabled buttons and inputs.

## 7. Document it

Add a row to the theme table in [Themes and display](gui/themes.md) — one line
on the character and when to use it. A theme nobody can find is a theme nobody
uses.

## Why the tests are strict

A theme that "looks fine" on one monitor can make a red LED invisible on
another. The contrast tests are the objective floor; they do not replace looking
at the actual screen in the lab.

## Next

- [Themes and display](gui/themes.md)
- [Testing and CI](reference/testing.md)
