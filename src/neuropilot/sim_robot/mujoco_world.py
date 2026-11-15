import math
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import mujoco
import mujoco.viewer
import numpy as np
from scipy.spatial.transform import Rotation

from . import config
from .utils.logging_utils import get_logger

log = get_logger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


class MuJoCoWorld:
    def __init__(
        self,
        use_gui: bool = True,
        end_effector_site_name: str = "coil_tcp_site",
        head_mesh_stl: Optional[str] = None,
        scene_name: str = "_generated_scene.xml",
        head_pose: Optional[Tuple[List[float], List[float]]] = None,
        base_pose: Optional[Tuple[List[float], List[float]]] = None,
    ):
        self.use_gui = use_gui
        self.end_effector_site_name = end_effector_site_name
        # Optional head phantom override (an STL path) replacing the default
        # head.stl, set from the project window's head mesh.
        self.head_mesh_stl = head_mesh_stl
        # The collision-test world writes its own scene file so it never
        # clobbers the live simulated robot's _generated_scene.xml.
        self.scene_name = scene_name
        # (position_m, orientation_deg) overrides; None = sim_robot config.
        self.head_pose = head_pose
        self.base_pose = base_pose
        # The MJCF base body may already carry a fixed frame rotation (the
        # Elfin's +90 deg).  Keep it so the collision test can convert world
        # targets into the IK chain's root frame rather than the body frame.
        self.base_xml_pose = None

        self.model: Optional[mujoco.MjModel] = None
        self.data: Optional[mujoco.MjData] = None

        self._joint_indices: List[int] = []
        self._joint_qpos_addrs: List[int] = []
        self._actuator_ids: List[int] = []

        self._robot_body_ids: List[int] = []
        self._head_body_ids: List[int] = []
        self._robot_geom_ids: List[int] = []
        self._head_geom_ids: List[int] = []
        # Body -> all its geoms, including invisible visual geoms.  The
        # contact-colour overlay tints the rendered link, not just the
        # collision hull.
        self._robot_body_geom_ids: Dict[int, List[int]] = {}
        self._robot_geom_original_rgba: Dict[int, np.ndarray] = {}

        self._ee_site_id: Optional[int] = None

        self._data_lock = threading.Lock()
        self._viewer_thread: Optional[threading.Thread] = None
        self._viewer_handle: Optional[mujoco.viewer.Handle] = None
        self._running = False

    def connect(self):
        self._build_model()
        if self.use_gui:
            self._start_viewer()

    def _start_viewer(self) -> None:
        if self._viewer_thread is not None:
            return
        self._running = True
        self._viewer_thread = threading.Thread(target=self._viewer_loop, daemon=True)
        self._viewer_thread.start()

    def _stop_viewer(self) -> None:
        """Stop the native viewer before the model is replaced.

        The passive viewer keeps the model it was launched with, so a head
        change needs a fresh viewer instance.  The controller's embedded view
        is independent and reloads the written scene on its own.
        """
        self._running = False
        handle = self._viewer_handle
        self._viewer_handle = None
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        thread = self._viewer_thread
        if thread is None:
            return
        if thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if thread.is_alive():
            log.warning("MuJoCo viewer did not stop within 2 s; a head "
                        "reload will wait until the next simulator start.")
        else:
            self._viewer_thread = None

    def _build_model(self) -> None:
        """Compose the scene, compile the model and index its structure.
        Uses self.head_mesh_stl as the head phantom when set."""
        scene_xml_path = self._compose_scene(self.head_mesh_stl)
        model = mujoco.MjModel.from_xml_path(scene_xml_path)
        # MuJoCo's compiled model defaults to a 640x480 offscreen buffer;
        # the camera stream renders at the configured (larger) size.
        model.vis.global_.offwidth = max(model.vis.global_.offwidth,
                                         config.CAMERA_STREAM_WIDTH)
        model.vis.global_.offheight = max(model.vis.global_.offheight,
                                          config.CAMERA_STREAM_HEIGHT)
        data = mujoco.MjData(model)
        base_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_BODY, config.ROBOT_BASE_BODY_NAME)
        if base_id >= 0:
            quat = model.body_quat[base_id]
            euler = Rotation.from_quat(
                [quat[1], quat[2], quat[3], quat[0]]).as_euler(
                    "xyz", degrees=True)
            self.base_xml_pose = (
                model.body_pos[base_id].copy(), euler.tolist())
        with self._data_lock:
            self.model = model
            self.data = data
        mujoco.mj_forward(self.model, self.data)

        # Config poses win over the MJCF defaults: this makes head placement
        # and robot base position config-driven instead of hardcoded in XML.
        self._apply_config_poses()

        self._index_joints()
        self._index_actuators()
        self._index_bodies_and_geoms()
        self._index_site()

    def reload_head(self, head_stl: Optional[str]) -> bool:
        """Replace the head phantom at runtime, or reset it with ``None``.

        The model is rebuilt and the native viewer is restarted when it is
        open.  The controller's embedded view reloads the regenerated scene
        independently.  Returns True on success.
        """
        if head_stl and not os.path.isfile(head_stl):
            log.error(f"Head mesh reload failed: file not found: {head_stl}")
            return False

        previous = self.head_mesh_stl
        self.head_mesh_stl = head_stl
        viewer_was_running = self._viewer_thread is not None
        if viewer_was_running:
            self._stop_viewer()
            if self._viewer_thread is not None:
                self.head_mesh_stl = previous
                return False

        try:
            self._build_model()
        except Exception as e:
            log.error(f"Head mesh reload failed: {e}")
            self.head_mesh_stl = previous
            try:
                self._build_model()
            except Exception as e2:
                log.error(f"Model restore failed: {e2}")
            if viewer_was_running:
                self._start_viewer()
            return False

        if viewer_was_running:
            self._start_viewer()
        if head_stl:
            log.info(f"Head phantom replaced: {head_stl}")
        else:
            log.info("Head phantom reset to the default head.stl")
        return True

    def _compose_scene(self, head_mesh_stl: Optional[str] = None) -> str:
        """Compose the scene MJCF from config: robot geometry (per ROBOT),
        optional head phantom, physics. Returns the path of the generated file.
        ``head_mesh_stl`` replaces the default phantom mesh in head.xml."""
        if not config.ROBOT_KNOWN:
            raise ValueError(
                f"ROBOT='{config.ROBOT}' is not a known robot. Known: "
                f"{sorted(config.ROBOT_MJCF)}.  Add a RobotSpec (geometry, "
                "URDF, IK chain) in neuropilot/sim_robot/robots.py -- see "
                "docs/ROBOTS.md -- and select it again.")
        robot_mjcf = config.ROBOT_MJCF[config.ROBOT]

        gravity = " ".join(f"{g:g}" for g in config.GRAVITY)
        composed_dir = os.path.join(PROJECT_ROOT, "assets", "mjcf")

        # Overview camera for the GUI stream: looks at the midpoint between
        # robot base and head from the front-left, slightly above.
        import numpy as _np
        base = _np.array(self.base_pose[0] if self.base_pose
                         else config.ROBOT_BASE_POSITION)
        head_pos = (self.head_pose[0] if self.head_pose
                    else config.HEAD_POSITION)
        head = _np.array(head_pos) + _np.array([0.0, 0.0, 0.3])
        look_at = (_np.array(config.CAMERA_STREAM_TARGET) if config.CAMERA_STREAM_TARGET
                   else (base + head) / 2.0)
        cam_pos = look_at + _np.array(config.CAMERA_STREAM_OFFSET)
        forward = look_at - cam_pos
        forward = forward / _np.linalg.norm(forward)
        up_world = _np.array([0.0, 0.0, 1.0])
        right = _np.cross(forward, up_world)
        right /= _np.linalg.norm(right)
        up = _np.cross(right, forward)
        pos_str = " ".join(f"{v:.3f}" for v in cam_pos)
        xyaxes_str = " ".join(f"{v:.3f}" for v in [*right, *up])
        gui_camera = (f'<camera name="{config.GUI_CAMERA_NAME}" mode="fixed" '
                      f'fovy="{config.CAMERA_STREAM_FOVY}" '
                      f'pos="{pos_str}" xyaxes="{xyaxes_str}"/>')

        def _include_for(path: str) -> str:
            """Include paths must be relative to the composed file's directory.

            MuJoCo treats ``\\`` as an escape character in XML attributes, so
            relpaths from ``os.path.relpath`` must use forward slashes (on
            Windows they otherwise come back with backslashes)."""
            rel = os.path.relpath(os.path.join(PROJECT_ROOT, path), composed_dir)
            return rel.replace(os.sep, "/")

        head_include = (
            f'<include file="{_include_for(config.HEAD_MJCF_PATH)}"/>'
            if config.HEAD_MJCF_PATH
            else ""
        )

        # Head mesh override: copy head.xml with the mesh file pointed at the
        # project-derived STL (absolute path, independent of the meshdir).
        # A collision-test scene gets its own override so it cannot replace
        # the live simulated robot's phantom.
        scene_stem = os.path.splitext(self.scene_name)[0]
        override_name = ("_head_override.xml" if scene_stem == "_generated_scene"
                         else f"{scene_stem}_head_override.xml")
        override_fn = os.path.join(composed_dir, override_name)
        if head_mesh_stl and config.HEAD_MJCF_PATH:
            import re
            from xml.sax.saxutils import escape as _xml_escape
            head_fn = os.path.join(PROJECT_ROOT, config.HEAD_MJCF_PATH)
            with open(head_fn, encoding="utf-8") as f:
                head_xml = f.read()
            # An absolute path is used here (independent of the meshdir); on
            # Windows it contains backslashes, but MuJoCo only accepts '/'
            # separators inside XML attributes (backslash is an escape char).
            mesh_fn = _xml_escape(os.path.abspath(head_mesh_stl).replace(os.sep, "/"),
                                  {'"': "&quot;"})
            head_xml, n = re.subn(
                r'(<mesh\s+file=")[^"]*(" name="head_mesh")',
                lambda m: m.group(1) + mesh_fn + m.group(2),
                head_xml,
            )
            if n != 1:
                raise ValueError(f"head.xml has no unique head_mesh asset ({n} matches).")
            with open(override_fn, "w", encoding="utf-8") as f:
                f.write(head_xml)
            head_include = f'<include file="{override_name}"/>'
        elif os.path.isfile(override_fn):
            # The generated override is an artefact of a previous project;
            # do not leave it behind once the default phantom is active.
            try:
                os.remove(override_fn)
            except OSError as e:
                log.warning(f"Could not remove stale head override: {e}")
        xml = f"""<mujoco model="{config.MODEL_NAME}">
  <include file="{_include_for(robot_mjcf)}"/>
  {head_include}

  <option gravity="{gravity}" timestep="{config.SIM_TIMESTEP}"
          integrator="implicitfast">
    <flag contact="enable"/>
  </option>

  <visual>
    <headlight ambient="0.4 0.4 0.4" diffuse="0.8 0.8 0.8" specular="0.2 0.2 0.2"/>
    <rgba haze="0.15 0.25 0.35 1"/>
    <quality shadowsize="4096"/>
  </visual>

  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.3 0.5 0.7" rgb2="1 1 1" width="512"
            height="3072" />
    <texture name="tex_checker" type="2d" builtin="checker" rgb1="0.2 0.3 0.4" rgb2="0.1 0.2 0.3"
             width="512" height="512"/>
    <material name="mat_checker" texture="tex_checker" texrepeat="5 5" texuniform="true" reflectance="0.2"/>
  </asset>

  <worldbody>
    <light pos="0 0 1.5" dir="0 0 -1" directional="true" />
    <geom name="floor" type="plane" size="0 0 0.05" pos="0 0 -1.0" material="mat_checker"/>

    <!-- World axis origin (RGB = XYZ) at (0, 0, 0) -->
    <geom name="axis_x" type="capsule" size="0.005" fromto="0 0 0  0.3 0 0"
          rgba="1 0 0 1" contype="0" conaffinity="0"/>
    <geom name="axis_y" type="capsule" size="0.005" fromto="0 0 0  0 0.3 0"
          rgba="0 1 0 1" contype="0" conaffinity="0"/>
    <geom name="axis_z" type="capsule" size="0.005" fromto="0 0 0  0 0 0.3"
          rgba="0 0 1 0.5" contype="0" conaffinity="0"/>

    <!-- Fixed overview camera for the GUI stream (robot + head in frame) -->
    {gui_camera}
  </worldbody>
</mujoco>
"""
        composed_path = os.path.join(composed_dir, self.scene_name)
        with open(composed_path, "w") as f:
            f.write(xml)
        return composed_path

    def _apply_config_poses(self) -> None:
        """Apply HEAD_POSITION/ORIENTATION and ROBOT_BASE_POSITION/ORIENTATION
        from config (in meters / degrees) to the model bodies."""
        def set_pose(body_name, position_m, orientation_deg):
            bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, body_name)
            if bid < 0:
                log.warning(f"Body '{body_name}' not found in the model -- config pose skipped.")
                return
            self.model.body_pos[bid][:] = position_m
            quat = Rotation.from_euler("xyz", orientation_deg, degrees=True).as_quat()  # [x, y, z, w]
            self.model.body_quat[bid][:] = [quat[3], quat[0], quat[1], quat[2]]        # MuJoCo: [w, x, y, z]

        base_pos, base_ori = (self.base_pose if self.base_pose
                              else (config.ROBOT_BASE_POSITION,
                                    config.ROBOT_BASE_ORIENTATION))
        set_pose(config.ROBOT_BASE_BODY_NAME, base_pos, base_ori)
        if config.HEAD_MJCF_PATH:
            head_pos, head_ori = (self.head_pose if self.head_pose
                                  else (config.HEAD_POSITION,
                                        config.HEAD_ORIENTATION))
            set_pose(config.HEAD_BODY_NAME, head_pos, head_ori)
        mujoco.mj_forward(self.model, self.data)

    def set_scene_poses(self, head_pose=None, base_pose=None) -> None:
        """Move the head and/or robot base without rebuilding the model.

        ``head_pose`` and ``base_pose`` are ``(position_m, orientation_deg)``.
        This is the fast path used by the collision-test sliders and jog
        buttons; the kinematics/collision geometry is re-evaluated with
        ``mj_forward`` after the body poses are changed.
        """
        if head_pose is not None:
            self.head_pose = (list(head_pose[0]), list(head_pose[1]))
        if base_pose is not None:
            self.base_pose = (list(base_pose[0]), list(base_pose[1]))
        if self.model is not None:
            self._apply_config_poses()

    def disconnect(self):
        self._stop_viewer()

    def viewer_handle_closed(self) -> bool:
        """True when the viewer window has been closed (e.g. Alt+F4)."""
        if self._viewer_handle is not None:
            return not self._viewer_handle.is_running()
        return False

    def _viewer_loop(self):
        with mujoco.viewer.launch_passive(self.model, self.data) as viewer:
            self._viewer_handle = viewer
            viewer.cam.lookat[:] = [0.2, -0.2, 0.3]
            viewer.cam.distance = 2.5
            viewer.cam.azimuth = 210.0      # horzonat angle
            viewer.cam.elevation = -35.0      # vertical angle
            while viewer.is_running() and self._running:
                with self._data_lock:
                    viewer.sync()
                time.sleep(1.0 / 60.0)

    def _index_joints(self):
        self._joint_indices = []
        self._joint_qpos_addrs = []
        for i in range(self.model.njnt):
            jnt = self.model.joint(i)
            # MuJoCo only has non-fixed joints in the joint list
            self._joint_indices.append(i)
            self._joint_qpos_addrs.append(int(jnt.qposadr[0]))

    def _index_actuators(self):
        self._actuator_ids = []
        joint_set = set(self._joint_indices)
        for i in range(self.model.nu):
            # Get the joint ID that this actuator controls
            actuator = self.model.actuator(i)
            # Check if this actuator targets one of our movable joints
            try:
                trntype = int(self.model.actuator_trntype[i])
                if trntype == 0:  # TRN_JOINT
                    jnt_id = int(self.model.actuator_trnid[i][0])
                    if jnt_id in joint_set:
                        self._actuator_ids.append(i)
            except Exception:
                pass

    def _index_bodies_and_geoms(self):
        """Index the robot and head by body identity, not by hard-coded names.

        The scene is composed per robot, so the arm's link names differ
        (Omron ``link_*``, UR ``*_link``, Elfin ``elfin_link*``, Dobot
        ``Link*``).  Every non-world, non-head body belongs to the robot.
        """
        self._robot_body_ids = []
        self._head_body_ids = []
        self._robot_geom_ids = []
        self._head_geom_ids = []
        self._robot_body_geom_ids = {}
        self._robot_geom_original_rgba = {}

        head_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, config.HEAD_BODY_NAME)
        for i in range(self.model.nbody):
            if i == 0:                       # world
                continue
            if i == head_id:
                self._head_body_ids.append(i)
            else:
                self._robot_body_ids.append(i)

        robot_set = set(self._robot_body_ids)
        head_set = set(self._head_body_ids)
        for i in range(self.model.ngeom):
            body_id = int(self.model.geom(i).bodyid[0])
            contype = int(self.model.geom(i).contype[0])
            if body_id in robot_set:
                self._robot_body_geom_ids.setdefault(body_id, []).append(i)
                self._robot_geom_original_rgba[i] = (
                    self.model.geom_rgba[i].copy())
                if contype > 0:
                    self._robot_geom_ids.append(i)
            elif body_id in head_set and contype > 0:
                self._head_geom_ids.append(i)

    def _index_site(self):
        try:
            self._ee_site_id = self.model.site(self.end_effector_site_name).id
        except Exception:
            self._ee_site_id = None

    def get_movable_joint_indices(self) -> List[int]:
        return list(self._joint_indices)

    def get_joint_positions(self) -> List[float]:
        if self.data is None:
            return []
        with self._data_lock:
            return [float(self.data.qpos[addr]) for addr in self._joint_qpos_addrs]

    def reset_joint_positions(self, joint_positions: List[float]):
        if self.data is None:
            return
        with self._data_lock:
            for addr, pos in zip(self._joint_qpos_addrs, joint_positions):
                self.data.qpos[addr] = pos
            for act_id, pos in zip(self._actuator_ids, joint_positions):
                self.data.ctrl[act_id] = pos
            mujoco.mj_forward(self.model, self.data)

    def set_joint_motor_targets(self, joint_targets: List[float], max_force: float = 500.0):
        if self.data is None:
            return
        with self._data_lock:
            for act_id, target in zip(self._actuator_ids, joint_targets):
                self.data.ctrl[act_id] = target

    def step(self, n_steps: int = 1):
        if self.data is None:
            return
        with self._data_lock:
            for _ in range(n_steps):
                mujoco.mj_step(self.model, self.data)

    def get_end_effector_pose(self) -> Tuple[List[float], List[float]]:
        if self.data is None or self._ee_site_id is None:
            raise RuntimeError("Robot not loaded or site not found")

        with self._data_lock:
            world_pos = self.data.site_xpos[self._ee_site_id].copy()
            site_mat = self.data.site_xmat[self._ee_site_id].reshape(3, 3).copy()

        world_euler_rad = Rotation.from_matrix(site_mat).as_euler("xyz")
        world_euler_deg = [math.degrees(v) for v in world_euler_rad]

        return world_pos.tolist(), world_euler_deg

    def move_coil_visual_to_pose(self, position_xyz_m: List[float], orientation_deg: List[float]):
        pass

    def get_robot_head_closest_distance(self, distance_threshold: float = 0.1) -> Optional[float]:
        if self.data is None or not self._robot_geom_ids or not self._head_geom_ids:
            return None

        min_dist = None
        with self._data_lock:
            fromto = np.zeros(6)
            for r_gid in self._robot_geom_ids:
                for h_gid in self._head_geom_ids:
                    dist = mujoco.mj_geomDistance(
                        self.model, self.data,
                        r_gid, h_gid,
                        distance_threshold, fromto,
                    )
                    if min_dist is None or dist < min_dist:
                        min_dist = dist

        # mj_geomDistance clamps its result to distance_threshold, so a value
        # at the threshold means "no closer than the search band", not a
        # 2 cm proximity reading.
        if min_dist is not None and min_dist < distance_threshold:
            return float(min_dist)
        return None

    def get_robot_head_body_distances(
        self, distance_threshold: float = 0.02
    ) -> Dict[int, float]:
        """Closest distance from each robot body to the head, in metres.

        Visual and collision geoms share a body, so the result can tint the
        rendered link.  Geoms farther than ``distance_threshold`` are omitted.
        """
        if self.data is None or not self._robot_geom_ids or not self._head_geom_ids:
            return {}

        body_dist: Dict[int, float] = {}
        with self._data_lock:
            fromto = np.zeros(6)
            for robot_gid in self._robot_geom_ids:
                body_id = int(self.model.geom_bodyid[robot_gid])
                for head_gid in self._head_geom_ids:
                    dist = float(mujoco.mj_geomDistance(
                        self.model, self.data,
                        robot_gid, head_gid,
                        distance_threshold, fromto,
                    ))
                    if dist > distance_threshold:
                        continue
                    previous = body_dist.get(body_id)
                    if previous is None or dist < previous:
                        body_dist[body_id] = dist

        # Contact records are authoritative for penetration depth.
        for contact in self.get_robot_head_contacts():
            for geom_id in (contact.get("geom1"), contact.get("geom2")):
                if geom_id not in self._robot_geom_ids:
                    continue
                body_id = int(self.model.geom_bodyid[int(geom_id)])
                dist = float(contact.get("dist", 0.0))
                previous = body_dist.get(body_id)
                if previous is None or dist < previous:
                    body_dist[body_id] = dist
        return body_dist

    def set_robot_body_colors(self, body_rgba: Dict[int, List[float]]) -> None:
        """Tint all geoms of the selected robot bodies.

        Call :meth:`restore_robot_colors` first when a body may have left the
        proximity band; that method restores the MJCF colours.
        """
        if self.model is None:
            return
        for body_id, rgba in body_rgba.items():
            for geom_id in self._robot_body_geom_ids.get(int(body_id), ()):
                self.model.geom_rgba[geom_id] = rgba

    def restore_robot_colors(self) -> None:
        """Restore every robot geom to its original MJCF colour."""
        if self.model is None:
            return
        for geom_id, rgba in self._robot_geom_original_rgba.items():
            self.model.geom_rgba[geom_id] = rgba

    def get_robot_head_contacts(self) -> List[dict]:
        if self.data is None or not self._robot_geom_ids or not self._head_geom_ids:
            return []

        contacts = []
        robot_set = set(self._robot_geom_ids)
        head_set = set(self._head_geom_ids)

        with self._data_lock:
            for i in range(self.data.ncon):
                c = self.data.contact[i]
                g1 = int(c.geom1)
                g2 = int(c.geom2)

                if (g1 in robot_set and g2 in head_set) or (g1 in head_set and g2 in robot_set):
                    force = np.zeros(6)
                    mujoco.mj_contactForce(self.model, self.data, i, force)
                    contacts.append({
                        "geom1": g1,
                        "geom2": g2,
                        "dist": float(c.dist),
                        "normal_force": float(np.linalg.norm(force[:3])),
                    })

        return contacts

    def get_link_count(self) -> int:
        if self.model is None:
            return 0
        return self.model.nbody

    def get_self_collision_contacts(self) -> list:
        robot_set = set(self._robot_geom_ids)
        contacts = []
        with self._data_lock:
            for i in range(self.data.ncon):
                c = self.data.contact[i]
                g1, g2 = int(c.geom1), int(c.geom2)
                if g1 in robot_set and g2 in robot_set:
                    contacts.append({"dist": float(c.dist)})
        return contacts
