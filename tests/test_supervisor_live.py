"""Live relay-line coalescing in the supervisor."""

import io

from neuropilot import supervisor


def _forward(topic, payload="{}"):
    return ("[09:24:58][SIM RELAY] "
            "Forwarding robot -> neuronavigation and pipeline: "
            f"{{'topic': '{topic}', 'data': {payload}}}")


def test_relay_forward_key_extracts_the_topic():
    key = supervisor._relay_forward_key(
        _forward("SIM - Robot to Neuronavigation: Tracking State"))
    assert key == (
        "Forwarding robot -> neuronavigation and pipeline",
        "SIM - Robot to Neuronavigation: Tracking State",
    )


def test_live_output_overwrites_repeated_topic_on_tty():
    stream = io.StringIO()
    live = supervisor._LiveOutput(stream, is_tty=True)
    key = ("Forwarding robot", "Tracking")
    live.feed("relay", key, "first")
    assert stream.getvalue() == "[relay] first"
    live.feed("relay", key, "second")
    assert "\r\x1b[2K" in stream.getvalue()
    assert "x2" in stream.getvalue()
    assert "second" in stream.getvalue()
    live.finish()
    assert stream.getvalue().endswith("\n")


def test_live_output_coalesces_without_tty():
    stream = io.StringIO()
    live = supervisor._LiveOutput(stream, is_tty=False)
    key = ("Forwarding robot", "Tracking")
    live.feed("relay", key, "first")
    live.feed("relay", key, "second")
    assert stream.getvalue() == ""
    live.finish()
    value = stream.getvalue()
    assert value.startswith("[relay] ")
    assert "x2" in value
    assert "second" in value
    assert value.endswith("\n")
