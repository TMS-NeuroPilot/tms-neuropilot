# main.py
# Starts the virtual neuronavigation client and connects it to relay_server_sim.

# main.py

import asyncio

from .sim_client import SimNeuronavigationClient
from .state import VirtualNeuronavigationState


async def main():
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