import math
from typing import List, Optional, Tuple
import os
import pybullet as p
import pybullet_data
from . import config
class PyBulletWorld:
    def __init__(
        self,
        robot_urdf_path: str,
        head_urdf_path: Optional[str] = None,
        coil_urdf_path: Optional[str] = None,
        use_gui: bool = True,
        time_step: float = 1.0 / 240.0,
        gravity: Tuple[float, float, float] = (0.0, 0.0, -9.81),
        end_effector_link_index: Optional[int] = None,
    ):
        self.robot_urdf_path = robot_urdf_path
        self.head_urdf_path = head_urdf_path
        self.coil_urdf_path = coil_urdf_path
        self.use_gui = use_gui
        self.time_step = time_step
        self.gravity = gravity
        self.end_effector_link_index = end_effector_link_index

        self.client_id: Optional[int] = None
        self.robot_id: Optional[int] = None
        self.head_id: Optional[int] = None
        self.coil_id: Optional[int] = None
        self.plane_id: Optional[int] = None

        self._joint_indices: List[int] = []

    def connect(self):
        if self.client_id is not None:
            return

        mode = p.GUI if self.use_gui else p.DIRECT
        self.client_id = p.connect(mode)

        #p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self.client_id)
        urdf_dir = os.path.dirname(os.path.abspath(self.robot_urdf_path))
        p.setAdditionalSearchPath(urdf_dir, physicsClientId=self.client_id)
        p.setGravity(*self.gravity, physicsClientId=self.client_id)
        p.setTimeStep(self.time_step, physicsClientId=self.client_id)
        p.configureDebugVisualizer(p.COV_ENABLE_GUI, 1 if self.use_gui else 0, physicsClientId=self.client_id)

    def disconnect(self):
        if self.client_id is not None:
            p.disconnect(self.client_id)
            self.client_id = None

    def load_scene(self):
        if self.client_id is None:
            raise RuntimeError("PyBullet client is not connected")

        #self.plane_id = p.loadURDF("plane.urdf", physicsClientId=self.client_id)
         # Use absolute path — no longer relying on search path for this
        plane_urdf = os.path.join(pybullet_data.getDataPath(), "plane.urdf")
        self.plane_id = p.loadURDF(plane_urdf, basePosition=config.FLOOR_POSITION, physicsClientId=self.client_id)

        # Robot base from config
        robot_pos = config.ROBOT_BASE_POSITION
        robot_ori = p.getQuaternionFromEuler(
            [math.radians(v) for v in config.ROBOT_BASE_ORIENTATION]
        )
        self.robot_id = p.loadURDF(
            self.robot_urdf_path,
            basePosition=robot_pos,
            baseOrientation=robot_ori,
            useFixedBase=True,
            physicsClientId=self.client_id,
        )

        # Head from config
        if self.head_urdf_path:
            head_pos = config.HEAD_POSITION
            head_ori = p.getQuaternionFromEuler(
                [math.radians(v) for v in config.HEAD_ORIENTATION]
            )
            self.head_id = p.loadURDF(
                self.head_urdf_path,
                basePosition=head_pos,
                baseOrientation=head_ori,
                useFixedBase=True,
                physicsClientId=self.client_id,
            )

        # Coil at a default position (can be adjusted)
        if self.coil_urdf_path:
            self.coil_id = p.loadURDF(
                self.coil_urdf_path,
                basePosition=[0.30, 0.0, 1.0],
                baseOrientation=p.getQuaternionFromEuler([0.0, 0.0, 0.0]),
                useFixedBase=True,
                physicsClientId=self.client_id,
            )

        self._joint_indices = self.get_movable_joint_indices()

    def get_movable_joint_indices(self) -> List[int]:
        if self.robot_id is None:
            return []

        joint_indices = []
        n_joints = p.getNumJoints(self.robot_id, physicsClientId=self.client_id)
        for joint_idx in range(n_joints):
            joint_info = p.getJointInfo(self.robot_id, joint_idx, physicsClientId=self.client_id)
            joint_type = joint_info[2]
            if joint_type != p.JOINT_FIXED:
                joint_indices.append(joint_idx)

        return joint_indices

    def get_joint_positions(self) -> List[float]:
        if self.robot_id is None:
            return []

        positions = []
        for joint_idx in self._joint_indices:
            joint_state = p.getJointState(self.robot_id, joint_idx, physicsClientId=self.client_id)
            positions.append(joint_state[0])
        return positions

    def reset_joint_positions(self, joint_positions: List[float]):
        if self.robot_id is None:
            return

        for joint_idx, joint_pos in zip(self._joint_indices, joint_positions):
            p.resetJointState(
                self.robot_id,
                joint_idx,
                joint_pos,
                physicsClientId=self.client_id,
            )

    def set_joint_motor_targets(self, joint_targets: List[float], max_force: float = 500.0):
        if self.robot_id is None:
            return

        for joint_idx, joint_target in zip(self._joint_indices, joint_targets):
            p.setJointMotorControl2(
                bodyUniqueId=self.robot_id,
                jointIndex=joint_idx,
                controlMode=p.POSITION_CONTROL,
                targetPosition=joint_target,
                force=max_force,
                physicsClientId=self.client_id,
            )

    def step(self, n_steps: int = 1):
        if self.client_id is None:
            return

        for _ in range(n_steps):
            p.stepSimulation(physicsClientId=self.client_id)

    def get_end_effector_pose(self) -> Tuple[List[float], List[float]]:
        if self.robot_id is None:
            raise RuntimeError("Robot not loaded")

        if self.end_effector_link_index is None:
            raise RuntimeError("end_effector_link_index must be set")

        link_state = p.getLinkState(
            self.robot_id,
            self.end_effector_link_index,
            computeForwardKinematics=True,
            physicsClientId=self.client_id,
        )

        world_pos = list(link_state[4])
        world_quat = list(link_state[5])
        world_euler_rad = p.getEulerFromQuaternion(world_quat)
        world_euler_deg = [math.degrees(v) for v in world_euler_rad]

        return world_pos, world_euler_deg

    def move_coil_visual_to_pose(self, position_xyz_m: List[float], orientation_deg: List[float]):
        if self.coil_id is None:
            return

        quat = p.getQuaternionFromEuler([math.radians(v) for v in orientation_deg])
        p.resetBasePositionAndOrientation(
            self.coil_id,
            position_xyz_m,
            quat,
            physicsClientId=self.client_id,
        )

    def get_robot_head_closest_distance(self, distance_threshold: float = 0.1) -> Optional[float]:
        if self.robot_id is None or self.head_id is None:
            return None

        closest_points = p.getClosestPoints(
            bodyA=self.robot_id,
            bodyB=self.head_id,
            distance=distance_threshold,
            physicsClientId=self.client_id,
        )

        if not closest_points:
            return None

        return min(point[8] for point in closest_points)

    def get_robot_head_contacts(self):
        if self.robot_id is None or self.head_id is None:
            return []

        return p.getContactPoints(
            bodyA=self.robot_id,
            bodyB=self.head_id,
            physicsClientId=self.client_id,
        )

    def get_link_count(self) -> int:
        if self.robot_id is None:
            return 0
        return p.getNumJoints(self.robot_id, physicsClientId=self.client_id)