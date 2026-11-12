"""The relay card on the Connections page."""

import pytest

from neuropilot.controller.systems.relay import RelaySystem
from neuropilot.controller.systems.system import SystemStatus

pytestmark = pytest.mark.gui


def test_relay_card_is_present(window):
    assert window.relayStatusLabel is not None
    assert window.relayRecoverButton is not None
    assert window.relay_info_cap_1 is not None


def test_relay_system_binds_to_the_card(window):
    relay = RelaySystem(window.update_system_status, simulation=True)
    window.initialize({relay: relay.ERROR_RECOVERIES})
    relay.set_system_status(SystemStatus.OK)
    assert window.relayStatusLabel.text() == "OK"
    assert window.relayStatusLabel.styleSheet()
    assert window.relayStatusLabel.property("role") == "value"
    assert window.relayLastUpdateLabel.property("role") == "mono"
    assert window.relay_ready is True
    assert "Relay" in window.groupBox_relay.title()


def test_an_unready_relay_blocks_start(window):
    window.relay_ready = False
    window.update_button_states()
    assert not window.start_btn.isEnabled()


def test_owned_relay_can_be_restarted_while_healthy(window):
    relay = RelaySystem(window.update_system_status, simulation=False)
    window.initialize({relay: relay.ERROR_RECOVERIES})
    relay.owned = True
    relay.set_system_status(SystemStatus.OK)
    assert window.relayRecoverButton.isEnabled()
    assert window.relayRecoverButton.text() == "Restart relay"
