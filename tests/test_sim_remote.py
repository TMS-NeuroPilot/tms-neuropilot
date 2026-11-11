"""The simulated relay client: fire-and-forget sending and frame handling."""

import asyncio

import pytest

from neuropilot.controller.sim_remote_connection import Remote


@pytest.fixture()
def remote():
    # Never connects; the socket client is inert until ``connect()``.
    return Remote("http://localhost:5000", verbose=False)


def test_send_while_disconnected_returns_false(remote):
    assert asyncio.run(remote.send_message("topic", {"x": 1})) is False


def test_disconnected_warning_is_logged_once(capsys):
    remote = Remote("http://localhost:5000", verbose=True)
    asyncio.run(remote.send_message("a", {}))
    asyncio.run(remote.send_message("b", {}))
    out = capsys.readouterr().out
    assert out.count("dropping message") == 1


def test_default_payload_is_an_empty_dict(remote):
    assert asyncio.run(remote.send_message("topic")) is False


def test_message_without_a_topic_is_ignored(remote):
    asyncio.run(remote.on_message_received({"data": {"x": 1}}))


@pytest.mark.parametrize("bad", [None, "text", 42, ["topic"]])
def test_non_object_messages_are_ignored(remote, bad):
    asyncio.run(remote.on_message_received(bad))          # must not raise


def test_unknown_topic_is_ignored(remote):
    called = []
    remote.register_handler("known", lambda payload: called.append(payload))
    asyncio.run(remote.on_message_received({"topic": "other", "data": {}}))
    assert called == []


def test_sync_handler_receives_the_payload(remote):
    called = []
    remote.register_handler("known", lambda payload: called.append(payload))
    asyncio.run(remote.on_message_received({"topic": "known", "data": {"a": 1}}))
    assert called == [{"a": 1}]


def test_async_handler_is_awaited(remote):
    called = []

    async def handler(payload):
        await asyncio.sleep(0)
        called.append(payload)

    remote.register_handlers({"known": handler})
    asyncio.run(remote.on_message_received({"topic": "known", "data": 2}))
    assert called == [2]


def test_handler_registration_overwrites(remote):
    first, second = [], []
    remote.register_handler("t", first.append)
    remote.register_handler("t", second.append)
    asyncio.run(remote.on_message_received({"topic": "t", "data": 1}))
    assert first == [] and second == [1]


def test_handler_exception_propagates_to_the_socket_layer(remote):
    def boom(payload):
        raise RuntimeError("handler bug")

    remote.register_handler("t", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(remote.on_message_received({"topic": "t", "data": {}}))
