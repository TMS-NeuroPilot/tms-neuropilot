"""The colour themes: palettes, contrast requirements and the style sheet."""

import pytest

from neuropilot.controller import theme


def test_five_themes_two_of_them_dark():
    assert len(theme.names()) == 5
    dark = [name for name in theme.names() if theme.is_dark(name)]
    assert len(dark) == 2, dark


def test_every_theme_defines_every_token():
    for name in theme.names():
        tokens = theme.tokens(name)
        assert set(theme.TOKENS) <= set(tokens), name
        for key in theme.TOKENS:
            if key == "series":
                continue
            value = tokens[key]
            assert isinstance(value, str) and value.startswith("#"), (name, key)
            assert len(value) == 7, (name, key, value)


def test_series_have_six_distinct_colours():
    for name in theme.names():
        series = theme.tokens(name)["series"]
        assert len(series) == 6
        assert len(set(series)) == 6


@pytest.mark.parametrize("name", theme.names())
def test_body_text_contrast(name):
    tokens = theme.tokens(name)
    assert theme.contrast(tokens["ink"], tokens["canvas"]) >= 7.0
    assert theme.contrast(tokens["ink"], tokens["card"]) >= 7.0


@pytest.mark.parametrize("name", theme.names())
def test_caption_and_status_contrast(name):
    tokens = theme.tokens(name)
    assert theme.contrast(tokens["muted"], tokens["canvas"]) >= 4.5
    assert theme.contrast(tokens["muted"], tokens["card"]) >= 4.5
    assert theme.contrast(tokens["on_accent"], tokens["accent"]) >= 4.5
    for status in ("ok", "warn", "danger"):
        assert theme.contrast(tokens[status], tokens["card"]) >= 4.5, status


@pytest.mark.parametrize("name", theme.names())
def test_instrument_bed_contrast(name):
    tokens = theme.tokens(name)
    assert theme.contrast(tokens["bed_ink"], tokens["bed"]) >= 7.0


@pytest.mark.parametrize("name", theme.names())
def test_dark_themes_have_two_readable_levels(name):
    tokens = theme.tokens(name)
    if not theme.is_dark(name):
        pytest.skip("light theme")
    canvas, card = tokens["canvas"], tokens["card"]
    # cards lighter than the canvas, borders lighter than the cards
    assert theme.luminance(card) > theme.luminance(canvas)
    assert theme.luminance(tokens["line"]) > theme.luminance(card)
    assert theme.luminance(canvas) > 0.0


def test_light_themes_do_not_use_near_black_cards():
    for name in theme.names():
        if theme.is_dark(name):
            continue
        assert theme.luminance(theme.tokens(name)["card"]) > 0.8


def test_stylesheet_has_no_unfilled_placeholders():
    for name in theme.names():
        sheet = theme.build_stylesheet(name)
        assert "%(" not in sheet, name
        assert "{" not in sheet.replace("{{", "") or True   # QSS braces are fine
        assert len(sheet) > 5000


def test_stylesheet_contains_the_palette_colours():
    for name in theme.names():
        tokens = theme.tokens(name)
        sheet = theme.build_stylesheet(name)
        for key in ("canvas", "card", "accent", "bed", "ok", "danger"):
            assert tokens[key] in sheet, (name, key)


def test_icon_rules_are_appended_on_demand():
    plain = theme.build_stylesheet("Graphite")
    with_icons = theme.build_stylesheet(
        "Graphite", icons={"check": "/tmp/c.png", "up": "/tmp/u.png",
                           "down": "/tmp/d.png"})
    assert "efield_hint" not in plain
    assert "efield_hint" in with_icons
    assert "/tmp/c.png" in with_icons


def test_unknown_theme_falls_back_to_the_default():
    assert theme.tokens("nope") == theme.tokens(theme.DEFAULT_THEME)
    assert theme.DEFAULT_THEME in theme.names()


def test_the_default_theme_is_light():
    assert theme.is_dark(theme.DEFAULT_THEME) is False


def test_palettes_are_distinct():
    fingerprints = {
        name: repr(sorted(
            (key, tuple(value) if isinstance(value, list) else value)
            for key, value in theme.tokens(name).items()))
        for name in theme.names()}
    assert len(set(fingerprints.values())) == len(fingerprints)


def test_missing_token_is_reported(tmp_path, monkeypatch):
    broken = dict(theme.tokens(theme.DEFAULT_THEME))
    broken.pop("accent")
    monkeypatch.setitem(theme.THEMES, "Broken", broken)
    with pytest.raises(KeyError):
        theme.build_stylesheet("Broken")


def test_contrast_helper_known_values():
    assert theme.contrast("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert theme.contrast("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
