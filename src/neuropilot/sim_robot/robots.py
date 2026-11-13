"""Everything robot-specific in one table.

The simulator itself is robot-agnostic: the MuJoCo scene discovers joints and
actuators from the model, the IK solver reads the URDF, and the relay protocol
only speaks poses.  What differs between robots is the geometry, the IK chain
and the frames — that is one :class:`RobotSpec` per robot.

Adding a robot (simulated):

1. put its MuJoCo model (with its meshes) under ``assets/mjcf/`` and, for the
   IK solver, its URDF under ``assets/urdf/``;
2. add a :class:`RobotSpec` to :data:`ROBOTS` below;
3. run ``python -m neuropilot.sim_robot.robots --check <key>``;
4. select it in Config › Lab › Robot (or set ``ROBOT=<key>`` in the lab
   profile / ``.env``).

See ``docs/ROBOTS.md`` for the conventions (units, frames, tool site) and for
the real-robot side (which lives in ``tms-robot-control``).
"""

from dataclasses import dataclass
from pathlib import Path
import os
import sys
import xml.etree.ElementTree as ET

# Assets are addressed relative to the sim_robot package (see config.py).
PACKAGE_ROOT = Path(__file__).resolve().parent

DEFAULT_ROBOT = "omron"

# tms-robot-control selects the driver family in its own `.env`.  Accept
# those names here, so one `ROBOT=` value works on both sides.
ALIASES = {
    "ur": "ur5",
    "elfin": "elfin5",
    "elfin_new_api": "elfin5",
    "dobot": "cr5",
}


@dataclass(frozen=True)
class RobotSpec:
    """One robot: geometry, IK chain and the frames the simulator needs."""

    key: str                          # value of ROBOT / lab profile
    label: str                        # shown in the GUI
    mjcf: str                         # relative to sim_robot/, with meshes
    urdf: str                         # relative to sim_robot/, for ikpy
    base_body: str                    # body in the MJCF that carries the base
    ee_site: str                      # site in the MJCF used as the tool point
    ik_active_links: tuple            # ikpy chain mask (one bool per chain link)
    ik_base_elements: tuple = ("base",)
    ik_elbow_up: bool = True
    # Room layout defaults (metres, degrees, XYZ Euler "sxyz").
    base_position: tuple = (0.0, 0.0, 0.0)
    base_orientation: tuple = (0.0, 0.0, 0.0)
    # Overview camera for the embedded view: look-at point (None = midpoint of
    # robot base and head) and the offset from it (metres).
    camera_target: tuple | None = None
    camera_offset: tuple = (0.35, -1.05, 0.20)
    max_reach_m: float | None = None  # informational (workspace check, docs)
    notes: str = ""


# ── the robots the simulator knows ─────────────────────────────────────
ROBOTS = {
    "omron": RobotSpec(
        key="omron",
        label="Omron TM5X-700",
        mjcf="assets/mjcf/robot_tm5x_700.xml",
        urdf="assets/urdf/robot_tm5x_700_v2.urdf",
        base_body="link_0",
        ee_site="coil_tcp_site",
        ik_active_links=(False, True, True, True, True, True, True, False, False),
        ik_base_elements=("link_0",),
        ik_elbow_up=True,
        base_position=(0.0, 0.0, 0.0),
        base_orientation=(0.0, 0.0, 0.0),
        camera_target=(0.22, -0.22, 0.15),
        camera_offset=(0.35, -1.05, 0.20),
        max_reach_m=0.70,
        notes=("6 joints. The coil flange and the B65 handle are part of the "
               "tool chain; coil_tcp_site is the stimulation point."),
    ),
    "ur5": RobotSpec(
        key="ur5",
        label="Universal Robots UR5",
        mjcf="assets/mjcf/ur5.xml",
        urdf="assets/urdf/ur5.urdf",
        base_body="base_link",
        ee_site="coil_tcp_site",
        ik_active_links=(False, False, True, True, True, True, True, True,
                         False, False, False),
        ik_base_elements=("base_link",),
        ik_elbow_up=True,
        base_position=(0.0, 0.0, 0.0),
        base_orientation=(0.0, 0.0, 0.0),
        camera_target=(0.22, -0.22, 0.15),
        camera_offset=(0.35, -1.05, 0.20),
        max_reach_m=0.85,
        notes=("UR5, upstream driver 'ur'. 5 kg payload, 850 mm reach, "
               "+/-0.1 mm repeatability (vendor data). The URDF carries the "
               "same B65 holder and coil_tcp_site as the Omron model."),
    ),
    "elfin5": RobotSpec(
        key="elfin5",
        label="Han's Robot Elfin E5",
        mjcf="assets/mjcf/elfin5.xml",
        urdf="assets/urdf/elfin5.urdf",
        base_body="elfin_base_link",
        ee_site="coil_tcp_site",
        ik_active_links=(False, False, True, True, True, True, True, True,
                         False, False),
        ik_base_elements=("elfin_base_link",),
        ik_elbow_up=True,
        # The Elfin URDF has a +90 deg z rotation on its base frame.
        base_position=(0.0, 0.0, 0.0),
        base_orientation=(0.0, 0.0, 90.0),
        camera_target=(0.22, -0.22, 0.15),
        camera_offset=(0.35, -1.05, 0.20),
        max_reach_m=0.80,
        notes=("Elfin E5, the arm used by the Aalto / BioMag Helsinki mTMS "
               "platform and deployed at the University of Tübingen "
               "(Matsuda et al. 2025, doi:10.1088/1361-6560/adf36e). "
               "6 joints, 5 kg payload, 800 mm reach, +/-0.05 mm "
               "repeatability. Upstream driver 'elfin' / 'elfin_new_api'."),
    ),
    "cr5": RobotSpec(
        key="cr5",
        label="Dobot CR5",
        mjcf="assets/mjcf/cr5.xml",
        urdf="assets/urdf/cr5.urdf",
        base_body="base_link",
        ee_site="coil_tcp_site",
        ik_active_links=(False, True, True, True, True, True, True, False),
        ik_base_elements=("base_link",),
        ik_elbow_up=True,
        base_position=(0.0, 0.0, 0.0),
        base_orientation=(0.0, 0.0, 0.0),
        camera_target=(0.22, -0.22, 0.15),
        camera_offset=(0.35, -1.05, 0.20),
        max_reach_m=0.90,
        notes=("Dobot CR5 (the bundled CR-series model), upstream driver "
               "'dobot'. 5 kg payload, 900 mm reach, +/-0.03 mm repeatability "
               "(vendor data). The URDF is Dobot's TCP-IP-ROS-6AXis "
               "description (MIT)."),
    ),
}


def keys():
    """Known robot keys, in menu order."""
    return list(ROBOTS)


def labels():
    """(key, label) pairs for the GUI."""
    return [(key, spec.label) for key, spec in ROBOTS.items()]


def normalize(key):
    """Canonical simulator key for a driver name or a registry key."""
    value = str(key).strip().lower()
    return ALIASES.get(value, value)


def get(key):
    """The spec for ``key``; KeyError with the known keys otherwise."""
    key = normalize(key)
    try:
        return ROBOTS[key]
    except KeyError:
        raise KeyError(
            f"ROBOT='{key}' is not a known robot. Known: {sorted(ROBOTS)}. "
            "Add a RobotSpec in neuropilot/sim_robot/robots.py (see "
            "docs/ROBOTS.md).") from None


def resolve(key):
    """Like :func:`get`, but falls back to the default robot."""
    try:
        return get(key)
    except KeyError:
        print(f"[WARN] {key!r} is not a known robot; using {DEFAULT_ROBOT!r} "
              f"(known: {sorted(ROBOTS)})")
        return ROBOTS[DEFAULT_ROBOT]


# ── validation ─────────────────────────────────────────────────────────

def _mjcf_names(path):
    """(site names, body names) declared directly in an MJCF file."""
    tree = ET.parse(path)
    root = tree.getroot()
    sites = {element.get("name") for element in root.iter("site")}
    bodies = {element.get("name") for element in root.iter("body")}
    return sites, bodies


def _urdf_links(path):
    root = ET.parse(path).getroot()
    links = [element.get("name") for element in root.iter("link")]
    joints = [element.get("name") for element in root.iter("joint")]
    return links, joints


def check(spec, root=None):
    """Problems with a spec's assets (empty list means it is usable).

    Everything that can be checked without starting the simulator: the files
    exist and parse, the tool site and base body are declared, the URDF has
    the base element, and -- when ikpy is installed -- the IK mask matches the
    chain length ikpy actually builds (the only authoritative count).
    """
    root = Path(root) if root is not None else PACKAGE_ROOT
    problems = []
    mjcf = root / spec.mjcf
    urdf = root / spec.urdf

    if not mjcf.is_file():
        problems.append(f"MuJoCo model missing: {mjcf}")
    else:
        try:
            sites, bodies = _mjcf_names(mjcf)
        except ET.ParseError as e:
            problems.append(f"MuJoCo model does not parse ({mjcf.name}): {e}")
        else:
            if spec.ee_site not in sites:
                problems.append(
                    f"{mjcf.name} has no <site name='{spec.ee_site}'> "
                    f"(sites: {sorted(filter(None, sites))})")
            if spec.base_body not in bodies:
                problems.append(
                    f"{mjcf.name} has no <body name='{spec.base_body}'>")

    if not urdf.is_file():
        problems.append(f"IK URDF missing: {urdf}")
    else:
        try:
            links, joints = _urdf_links(urdf)
        except ET.ParseError as e:
            problems.append(f"IK URDF does not parse ({urdf.name}): {e}")
        else:
            if spec.ik_base_elements and spec.ik_base_elements[0] not in links:
                problems.append(
                    f"{urdf.name} has no link '{spec.ik_base_elements[0]}' "
                    f"(links: {links})")
            chain_length = _ikpy_chain_length(spec, urdf, problems)
            if chain_length is not None:
                if chain_length != len(spec.ik_active_links):
                    problems.append(
                        f"IK mask has {len(spec.ik_active_links)} entries but "
                        f"the ikpy chain from '{spec.ik_base_elements[0]}' "
                        f"has {chain_length} links -- one entry per link")
            elif not (len(joints) <= len(spec.ik_active_links) <= len(links)):
                problems.append(
                    f"IK mask has {len(spec.ik_active_links)} entries but "
                    f"{urdf.name} has {len(joints)} joints / {len(links)} "
                    "links -- ikpy needs one entry per chain element")

    if not 3 <= len(spec.ik_active_links):
        problems.append("IK mask needs at least three entries")
    for name, value in (("base_position", spec.base_position),
                        ("base_orientation", spec.base_orientation),
                        ("camera_offset", spec.camera_offset)):
        if len(value) != 3:
            problems.append(f"{name} must have three numbers, got {value!r}")
    return problems


def _ikpy_chain_length(spec, urdf, problems):
    """Length of the ikpy chain, or None when ikpy is not installed."""
    try:
        from ikpy.chain import Chain
    except ImportError:
        return None
    try:
        chain = Chain.from_urdf_file(
            str(urdf), base_elements=list(spec.ik_base_elements),
            active_links_mask=list(spec.ik_active_links))
    except Exception as e:                      # noqa: BLE001 - report anything
        problems.append(f"ikpy cannot build the chain from {urdf.name}: {e}")
        return None
    return len(chain.links)


def describe(spec):
    """One-screen summary for the CLI."""
    lines = [
        f"{spec.key}: {spec.label}",
        f"  MuJoCo model    {spec.mjcf}",
        f"  IK URDF         {spec.urdf}",
        f"  base body       {spec.base_body}",
        f"  tool site       {spec.ee_site}",
        f"  IK mask         {list(spec.ik_active_links)}"
        f"  base element {list(spec.ik_base_elements)}"
        f"  elbow {'up' if spec.ik_elbow_up else 'down'}",
        f"  base pose       {list(spec.base_position)} m, "
        f"{list(spec.base_orientation)} deg",
        f"  camera          target {list(spec.camera_target) if spec.camera_target else 'midpoint'}"
        f"  offset {list(spec.camera_offset)}",
    ]
    if spec.max_reach_m:
        lines.append(f"  reach           ~{spec.max_reach_m:.2f} m")
    if spec.notes:
        lines.append(f"  notes           {spec.notes}")
    return "\n".join(lines)


def _main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    rest = [a for a in argv if a != "--check"]
    if "--list" in rest or not rest:
        print("Known robots:", ", ".join(keys()))
        print()
        for key in keys():
            print(describe(ROBOTS[key]))
            print()
        return 0
    failures = 0
    for key in rest:
        try:
            spec = get(key)
        except KeyError as e:
            print(e.args[0])
            return 2
        problems = check(spec)
        print(describe(spec))
        if problems:
            failures += 1
            for problem in problems:
                print(f"  [ERROR] {problem}")
        else:
            print("  [OK] assets and frames look usable")
        print()
    return 1 if failures and check_only else 0


if __name__ == "__main__":
    raise SystemExit(_main())
