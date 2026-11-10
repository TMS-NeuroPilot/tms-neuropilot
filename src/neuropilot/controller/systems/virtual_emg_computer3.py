import numpy as np
import pandas as pd
from ..systems.system import System, SystemStatus
from pynibs.expio.Mep import get_virtual_mep_tvs, scale_e_for_dvs


class VirtualEMGComputer2(System):
    NAME = "Virtual EMG Computer 3"
    ERROR_RECOVERIES = {}

    def __init__(self, update_control_panel_func=None):
        super().__init__(update_control_panel_func=update_control_panel_func)

        self.e_matrix = None
        self.current_coil_placement_idx = 0

        # Element indices mapping muscles to E-field matrix columns
        self.muscle_elements = {
            "ADC 0": 10227,
            "ADC 1": 2997,
            "ADC 2": 9085,
        }

    def set_e_matrix(self, e_matrix):
        """Called when user uploads E-field matrix via GUI"""
        self.e_matrix = e_matrix
        print(f"E-field matrix set. Shape: {e_matrix.shape}")

    def try_connect(self):
        super().set_system_status(SystemStatus.OK)

    def recover(self, recovery):
        self.try_connect()

    async def check_system(self):
        if hasattr(self, 'recovery_queue') and self.recovery_queue:
            self.recovery_queue.popleft()
        super().set_system_status(SystemStatus.OK)

    def set_current_state(self, coil_placement_idx):
        self.current_coil_placement_idx = coil_placement_idx
        print("HEREEEEEEEEEE", f"Current coil placement index: {self.current_coil_placement_idx}")

    def e_val_scaled(self, e_field_col, e_val, mt=60):
        threshold = mt/100
        # example e_field_col= [40 50 60 70 80] not scaled
        e_field_col = e_field_col / max(e_field_col)  # [0.5   0.625 0.75  0.875 1.   ]

        e_field_col = (e_field_col-threshold)/max(e_field_col-threshold)   #[-0.25    0.0625  0.375   0.6875  1.    ]

        e_field_col = np.where(e_field_col > 0, e_field_col, 0) # [0.     0.0625 0.375  0.6875 1.    ]
        print("e_field_col11", e_field_col, e_field_col.shape)

        return e_field_col[e_val]



    def get_latest_emg_df(self, idx=None):
        if self.e_matrix is None:
            raise ValueError("E-field matrix not set. Call set_e_matrix() first.")

        vpps = {}
        for name, elem_idx in self.muscle_elements.items():
            # Get E-field at this element for current placement
            e_val = self.e_matrix[self.current_coil_placement_idx, elem_idx]
            print("this is the e_val", e_val)
            e_field_col = self.e_matrix[:, elem_idx]

            #print("this is the e_field_col", e_field_col)

            # Normalize to [0,1] (0 = motor threshold)
            # e_normalized = scale_e_for_dvs(e_field, mt=60, upper_limit=100)
            e_normalized = self.e_val_scaled(e_field_col, self.current_coil_placement_idx, mt=60)
            print("this is the e_normalized", e_normalized)

            # Generate MEP using TVS model
            mep_mV = get_virtual_mep_tvs(
                np.array([e_normalized]),
                trial_variability=True
            )

            print("this is the mep_mV", mep_mV)

            # Convert mV to V and cap
            # vpps[name] = max(mep_mV[0] / 1000, 0.0)
            vpps[name] = max(mep_mV[0], 0.0)
            print("this is the vpps[name]",vpps[name])

        return self._generate_polyphasic_emg(
            vpps["ADC 0"], vpps["ADC 1"], vpps["ADC 2"]
        )

    def _generate_polyphasic_emg(self, vpp_a, vpp_b, vpp_c,
                                 duration=0.7, sample_rate=4000):
        # Reuse from original VirtualEMGComputer
        t = np.linspace(0, duration, int(duration * sample_rate))

        def make_wave(vpp):
            center = 0.525
            width = 0.005
            freq = 150
            env = np.exp(-((t - center) ** 2) / (2 * width ** 2))
            wave = np.sin(2 * np.pi * freq * t) * env
            return (wave * (vpp / 2.0)) + np.random.normal(0, 0.001, len(t))

        return pd.DataFrame({
            "Time": t,
            "ADC 0": make_wave(vpp_a),
            "ADC 1": make_wave(vpp_b),
            "ADC 2": make_wave(vpp_c)
        })