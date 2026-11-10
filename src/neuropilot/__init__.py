"""NeuroPilot — guided online TMS mapping with online field optimization.

One suite, four components:

- ``neuropilot.controller``  experiment orchestrator (PyQt5 GUI, qasync backend)
- ``neuropilot.sim_relay``   simulated relay server (Socket.IO hub)
- ``neuropilot.sim_robot``   virtual robot (MuJoCo + PyBullet, URDF IK)
- ``neuropilot.sim_nav``     virtual neuronavigation (head tracking, targets)

``python -m neuropilot`` opens the mode selector; ``neuropilot sim`` starts
the whole simulated stack with one command.
"""

__version__ = "0.1.0"
