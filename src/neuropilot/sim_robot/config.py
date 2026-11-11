import os

# ─────────────────────────────────────────────
# Relay server
# ─────────────────────────────────────────────
RELAY_HOST = "127.0.0.1"
RELAY_PORT = 5000

# ─────────────────────────────────────────────
# Robot geometry (generic — mirrors tms-robot-control's ROBOT field)
# ─────────────────────────────────────────────
# tms-robot-control's .env defines which robot is used (ROBOT='omron', 'elfin',
# 'dobot', 'ur', ...). The sim honors the same definition: ROBOT here falls back
# to the value in ../tms-robot-control/.env, and maps to the robot's MuJoCo
# geometry (MJCF: meshes + joints + actuators + self-collision excludes).
# Adding a new geometry = adding its MJCF and a mapping entry here.
ROBOT = os.getenv("ROBOT", "")

def _robot_from_tms_robot_control_env() -> str:
    """Read ROBOT from tms-robot-control's .env (sibling clone), if present."""
    try:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tms-robot-control", ".env")
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ROBOT"):
                    _, _, value = line.partition("=")
                    return value.strip().strip("'\"").lower()
    except OSError:
        pass
    return ""

ROBOT = (ROBOT or _robot_from_tms_robot_control_env() or "omron").lower()

ROBOT_MJCF = {
    "omron": "assets/mjcf/robot_tm5x_700.xml",
    # add other geometries here as their MJCFs are added, e.g.:
    # "elfin": "assets/mjcf/elfin.xml",
}

# ─────────────────────────────────────────────
# Scene composition (generic — driven by the entries above)
# ─────────────────────────────────────────────
MODEL_NAME = f"Robo-TMS Virtual Twin ({ROBOT})"
HEAD_MJCF_PATH = "assets/mjcf/head.xml"   # set to None to simulate without the head phantom
HEAD_BODY_NAME = "head_link"
ROBOT_BASE_BODY_NAME = "link_0"

# ─────────────────────────────────────────────
# Asset paths
# ─────────────────────────────────────────────
# URDF paths (kept for ikpy IK solver — reads URDF independently)
ROBOT_URDF_PATH = "assets/urdf/robot_tm5x_700_v2.urdf"

# ─────────────────────────────────────────────
# MuJoCo world
# ─────────────────────────────────────────────
USE_GUI              = False   # the pipeline GUI shows the robot view via the camera stream; --gui re-enables the native MuJoCo viewer for debugging
SIM_TIMESTEP         = 0.002
GRAVITY              = (0.0, 0.0, -9.81)
END_EFFECTOR_SITE_NAME = "coil_tcp_site"
ACTUATOR_KP          = 200.0
ACTUATOR_KV          = 10.0

# ─────────────────────────────────────────────
# GUI camera stream (fixed overview camera, JPEG over the relay)
# ─────────────────────────────────────────────
GUI_CAMERA_NAME      = "gui_cam"
CAMERA_STREAM_WIDTH  = 1280
CAMERA_STREAM_HEIGHT = 960
CAMERA_STREAM_FPS    = 10.0
CAMERA_STREAM_QUALITY = 85
CAMERA_STREAM_FOVY   = 55
# Overview camera placement: look-at point (None = midpoint of robot base
# and head, slightly above) and the camera position relative to it.
CAMERA_STREAM_TARGET = [0.22, -0.22, 0.15]
CAMERA_STREAM_OFFSET = [0.35, -1.05, 0.20]

# ─────────────────────────────────────────────
# Room layout (edit these to match physical room)
# ─────────────────────────────────────────────
ROBOT_BASE_POSITION = [0.0, 0.0, 0.0]       # [x, y, z] in meters — robot base in world
ROBOT_BASE_ORIENTATION = [0.0, 0.0, 0.0]    # [rx, ry, rz] in degrees — robot base rotation

HEAD_POSITION = [0.4, -0.4, 0.0]           # [x, y, z] in meters — SimNIBS origin in world
HEAD_ORIENTATION = [0.0, 0.0, -90.0]          # [rx, ry, rz] in degrees — head rotation

FLOOR_POSITION = [0.0, 0.0, -1.5]           # ground plane 1.5m below robot
# ─────────────────────────────────────────────
# IK solver (ikpy — reads URDF, independent of physics engine)
# ─────────────────────────────────────────────
IK_ACTIVE_LINKS_MASK = [False, True, True, True, True, True, True, False, False]     # for "assets/urdf/robot_tm5x_700_v2.urdf"
IK_BASE_ELEMENTS     = ["link_0"]      # set to e.g. ["base_link"] if needed
IK_ELBOW_UP          = True            # True = elbow up (joint_3 positive), False = elbow down
IK_MAX_RETRIES       = 10              # max retries to find desired configuration

# ─────────────────────────────────────────────
# Controller loop intervals (seconds)
# ─────────────────────────────────────────────
CONTROL_INTERVAL_SEC = 0.05       # 20 Hz — how often step_control() runs
PUBLISH_INTERVAL_SEC = 0.05       # 20 Hz — how often tracking state is published
HEALTH_INTERVAL_SEC  = 1.0        # 1 Hz  — how often health status is published

# ─────────────────────────────────────────────
# Collision / contact thresholds
# ─────────────────────────────────────────────
COLLISION_DISTANCE_THRESHOLD_M = 0.01   # 1 cm — below this = collision
PENTRATION_TOLERANCE = -0.004 # ( ALLOWS 4 mm PENETRATION FOR COIL CONTACT)
CONTACT_FORCE_SCALE            = 10.0   # multiplier: normal_force → force_feedback value

# ─────────────────────────────────────────────
# Crane-path planning
# ─────────────────────────────────────────────
SAFE_HEIGHT_M                   = 0.35        # z (m) above head for crane-path clearance
CRANE_DISPLACEMENT_THRESHOLD_MM = 20.0        # mm — below this = direct interpolation (no crane)
PATH_INTERPOLATION_STEPS        = 30          # steps per path segment (tweak for visual speed)

# ─────────────────────────────────────────────
# Press-to-contact (after reaching a target; mirrors the real robot's
# pressure PID — the coil origin sits above the skin contact point)
# ─────────────────────────────────────────────
PRESS_ENABLED           = True
PRESS_FORCE_THRESHOLD   = 1.5   # pipeline stalls below force_feedback > 1
PRESS_STEP_MM           = 2.0
PRESS_MAX_DEPTH_MM      = 30.0

# ─────────────────────────────────────────────
# Incoming topics (robot sim listens to these)
# ─────────────────────────────────────────────
TOPIC_CREATE_MARKER  = "External Controller to Neuronavigation: Create Marker"
TOPIC_SET_TARGET     = "Neuronavigation to Robot: Set target"
TOPIC_PRESS_BUTTON   = "Press robot button"
TOPIC_SET_OBJECTIVE  = "Neuronavigation to Robot: Set objective"
TOPIC_STOP           = "STOP"
TOPIC_SET_HEAD_MESH  = "Pipeline to Robot: Set head mesh"

# Speed ratios broadcast by the GUI (must match pipeline_controller.py verbatim)
TOPIC_SET_FREE_DRIVE = "Neuronavigation to Robot: Set free drive"
TOPIC_SET_DEFAULT_SPEED = "GUI to Robot: set default speed robot"
TOPIC_SET_TUNING_SPEED  = "GUI to Robot: set tuning speed robot"
# The GUI's default-speed slider position that corresponds to the sim's
# baseline path pace (the slider sends ratio = value/100).
SPEED_BASE_RATIO = 0.4

# Outgoing: GUI camera stream (consumed by the pipeline's robot view panel)
TOPIC_CAMERA_FRAME   = "SIM - Robot to Pipeline: Camera frame"

# ─────────────────────────────────────────────
# Head phantom override (set from the project window's head mesh)
# ─────────────────────────────────────────────
# The controller publishes the project head mesh on TOPIC_SET_HEAD_MESH; the
# converted phantom is persisted here so a simulator restart picks it up.
HEAD_OVERRIDE_FILE = os.path.join(os.path.expanduser("~"), ".neuropilot",
                                  "sim_head_override.json")

# ─────────────────────────────────────────────
# Outgoing topics (robot sim publishes these)
# ─────────────────────────────────────────────
TOPIC_TRACKING_STATE = "SIM - Robot to Neuronavigation: Tracking State"
TOPIC_FORCE_FEEDBACK = "Robot to Neuronavigation: Send force sensor data"
TOPIC_HEALTH_STATUS  = "Robot to Pipeline: Health status"
