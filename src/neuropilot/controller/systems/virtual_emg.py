
import numpy as np
import pandas as pd
from ..systems.system import System, SystemStatus
from pynibs.expio.Mep import get_virtual_mep_tvs, scale_e_for_dvs


class VirtualEMG(System):
    NAME = "Virtual EMG"
    DESCRIPTION = "Simulated (E-field driven)"
    ERROR_RECOVERIES = {}

    def __init__(self, update_control_panel_func=None):
        super().__init__(update_control_panel_func=update_control_panel_func)

        self.e_matrix = None
        self.current_coil_placement_idx = 0
        self.stimulator_amplitude = None


        # Element indices mapping muscles to E-field matrix columns
        self.muscle_elements = {
            "ADC 0": 5208,
            "ADC 1": 5165,
            "ADC 2": 4456,
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

    def set_current_state(self, coil_placement_idx,stimuator_amplitude):
        self.current_coil_placement_idx = coil_placement_idx
        self.stimulator_amplitude = stimuator_amplitude
        print("HEREEEEEEEEEE", f"Current coil placement index: {self.current_coil_placement_idx}")

    def get_latest_emg_df(self, idx=None, e_field_for_mep = None):
        if self.e_matrix is None:
            raise ValueError("E-field matrix not set. Call set_e_matrix() first.")

        vpps = {}
        for name, elem_idx in self.muscle_elements.items():
            # Get E-field at this element for current placement
            if e_field_for_mep is not None:
                print(f"Shape of e_field_for_mep: {e_field_for_mep}")
                e_field = e_field_for_mep[elem_idx]
            else:
                e_field = self.e_matrix[self.current_coil_placement_idx, elem_idx]*1.4*self.stimulator_amplitude #1.4 to convert from (0-100)stimulator to (0-100) A/us
            print("this is the e_field",e_field)

            # Normalize to [0,1] (0 = motor threshold)
            e_normalized = scale_e_for_dvs(e_field, mt=60, upper_limit=100)
            e_normalized = np.clip(e_normalized, 0,1)
            print("this is the e_normalized", e_normalized)

            # Generate MEP using TVS model
            mep_mV = get_virtual_mep_tvs(
                np.array([e_normalized]),
                trial_variability=True
            )

            print("this is the mep_mV", mep_mV)

            # Convert mV to V and cap
            #vpps[name] = max(mep_mV[0] / 1000, 0.0)
            vpps[name] = max(mep_mV[0] , 0.0)
            print(vpps[name])

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