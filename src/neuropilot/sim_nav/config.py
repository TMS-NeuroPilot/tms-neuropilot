# config.py
#Stores simple thresholds like:

    #position tolerance in mm,

    #rotation tolerance in degrees,

    #relay URL.



# config.py

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}"

POSITION_TOL_MM = 5.0
ORIENTATION_TOL_DEG = 5.0

FROM_EVENT = "from_neuronavigation"
TO_EVENT = "to_neuronavigation"

TOPIC_CREATE_TARGET = "External Controller to Neuronavigation: Create Marker"
TOPIC_COIL_AT_TARGET = "From Neuronavigation: Coil at target"
TOPIC_REALIZED_TARGET = "From Neuronavigation: Coil target created"
TOPIC_STIM_MARKER = "Create marker"

# Richer sim message from tms-robot-sim
TOPIC_SIM_TRACKING_STATE = "SIM - Robot to Neuronavigation: Tracking State"

# Head position and orientation in PyBullet world (must match tms-robot-sim/config.py)
HEAD_POSITION = [0.4, -0.4, 0.0]       # [x, y, z] in meters — SimNIBS origin in world
HEAD_ORIENTATION = [0.0, 0.0, -90.0]   # [rx, ry, rz] in degrees — head rotation