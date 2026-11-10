"""Virtual neuronavigation: a stand-in for Invesalius that speaks the
neuronavigation role on the relay, replacing the real navigation system in
simulated pipeline runs.

Launched as ``python -m neuropilot.sim_nav`` (the ``neuropilot sim``
supervisor starts it in parallel with the virtual robot). The relay address
and the simulated tracking/registration behaviour are configured in the
package's ``config`` / ``sim_client`` modules.
"""

import asyncio

from .sim_client import SimNeuronavigationClient
from .state import VirtualNeuronavigationState


async def main():
    """Create the virtual navigation state, connect to the relay and keep
    the process alive while the client's send/receive loops run."""
    state = VirtualNeuronavigationState()
    client = SimNeuronavigationClient(state=state)
    await client.connect()

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[virtual_neuronavigation] Stopped by user")