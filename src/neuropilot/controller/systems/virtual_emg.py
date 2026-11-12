
import os

import numpy as np
import pandas as pd
from ..systems.system import System, SystemStatus
from pynibs.expio.Mep import get_virtual_mep_tvs, scale_e_for_dvs


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class VirtualEMG(System):
    NAME = "Virtual EMG"
    DESCRIPTION = "Simulated (E-field driven)"
    ERROR_RECOVERIES = {}

    def __init__(self, update_control_panel_func=None):
        super().__init__(update_control_panel_func=update_control_panel_func)

        self.e_matrix = None
        self.current_coil_placement_idx = 0
        self.stimulator_amplitude = None

        # Simulated-MEP tuning. These are read once at construction; change
        # them in .env and restart the controller. The defaults are the values
        # the simulator has always used.
        self.noise_mv = float(os.getenv("VIRTUAL_MEP_NOISE_MV", "0.001"))
        self.trial_variability = _env_bool("VIRTUAL_MEP_TRIAL_VARIABILITY", True)
        self.mt = float(os.getenv("VIRTUAL_MEP_MT", "60"))
        self.upper_limit = float(os.getenv("VIRTUAL_MEP_UPPER_LIMIT", "100"))
        self.efield_scale = float(os.getenv("VIRTUAL_MEP_EFIELD_SCALE", "1.4"))

        # The channel count comes from .env (EMG_CHANNELS, comma separated --
        # the entries are the *display* names, e.g. FDI,APB,ADM). The data
        # layer always speaks ADC: EMG data columns and keys are
        # "ADC 0..N-1", and only the GUI labels and the results output use
        # the display names. The cortical source element per channel is
        # configured in the project window (element_id or xyz -> closest
        # element) and assigned positionally via set_channel_elements().
        self.display_names = [n.strip() for n in
                              os.getenv("EMG_CHANNELS", "ADC 0,ADC 1,ADC 2").split(",")
                              if n.strip()]
        self.channel_count = len(self.display_names)
        self.data_channel_names = [f"ADC {i}" for i in range(self.channel_count)]
        default_elements = [5208, 5165, 4456]
        self.channel_elements = (default_elements[:self.channel_count]
                                 + [None] * max(0, self.channel_count - len(default_elements)))
        if any(e is None for e in self.channel_elements):
            print("WARNING: More EMG channels configured than default sources -- "
                  "set the sources in the project window.")

    def _publish_details(self):
        sources = ", ".join(str(e) for e in self.channel_elements if e is not None)
        self.set_details({
            "Backend": "Simulated (E-field driven)",
            "Channels": f"{', '.join(self.display_names)} ({self.channel_count})",
            "Sources": sources or "not set",
            "Sample rate": "4 kHz",
            "Segment": "0.7 s",
        })

    def set_channel_elements(self, elements):
        """Assign one cortical source element per channel (positional, in the
        order of the data channels). Raises on a count mismatch."""
        if len(elements) != self.channel_count:
            raise ValueError(
                f"EMG source count ({len(elements)}) does not match the "
                f"channel count ({self.channel_count})"
            )
        self.channel_elements = list(elements)
        self._publish_details()
        for key, elem in zip(self.data_channel_names, self.channel_elements):
            print(f"EMG channel '{key}' -> element {elem}")

    def display_name_map(self):
        """Mapping of data channel keys ('ADC 0'...) to display names."""
        return {key: name for key, name in zip(self.data_channel_names, self.display_names)}

    def set_e_matrix(self, e_matrix):
        """Called when user uploads E-field matrix via GUI"""
        self.e_matrix = e_matrix
        print(f"E-field matrix set. Shape: {e_matrix.shape}")

    def try_connect(self):
        self._publish_details()
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

    def get_latest_emg_df(self, idx=None, e_field_for_mep=None, after=None):
        """Synthesise the sweep for the current coil placement.

        ``after`` is part of the real EMG's interface (the files that existed
        before the pulse); the simulated sweep is generated on demand, so it
        is ignored.
        """
        if self.e_matrix is None:
            raise ValueError("E-field matrix not set. Call set_e_matrix() first.")

        if any(e is None for e in self.channel_elements):
            raise ValueError("EMG channel sources not fully configured -- "
                             "set them in the project window.")

        vpps = {}
        for name, elem_idx in zip(self.data_channel_names, self.channel_elements):
            # Get E-field at this element for current placement
            if e_field_for_mep is not None:
                print(f"Shape of e_field_for_mep: {e_field_for_mep}")
                e_field = e_field_for_mep[elem_idx]
            else:
                e_field = (
                    self.e_matrix[self.current_coil_placement_idx, elem_idx]
                    * self.efield_scale
                    * self.stimulator_amplitude
                )
            print("this is the e_field",e_field)

            # Normalize to [0,1] (0 = motor threshold)
            e_normalized = scale_e_for_dvs(
                e_field, mt=self.mt, upper_limit=self.upper_limit)
            e_normalized = np.clip(e_normalized, 0,1)
            print("this is the e_normalized", e_normalized)

            # Generate MEP using TVS model
            mep_mV = get_virtual_mep_tvs(
                np.array([e_normalized]),
                trial_variability=self.trial_variability,
            )

            print("this is the mep_mV", mep_mV)

            # Convert mV to V and cap
            #vpps[name] = max(mep_mV[0] / 1000, 0.0)
            vpps[name] = max(mep_mV[0] , 0.0)
            print(vpps[name])

        return self._generate_polyphasic_emg(vpps)

    def _generate_polyphasic_emg(self, vpps,
                                 duration=0.7, sample_rate=4000):
        # One polyphasic burst per configured channel (names from .env,
        # cortical sources from the project window).
        t = np.linspace(0, duration, int(duration * sample_rate))

        def make_wave(vpp):
            center = 0.525
            width = 0.005
            freq = 150
            env = np.exp(-((t - center) ** 2) / (2 * width ** 2))
            wave = np.sin(2 * np.pi * freq * t) * env
            return (wave * (vpp / 2.0)) + np.random.normal(0, self.noise_mv, len(t))

        data = {"Time": t}
        for name, vpp in vpps.items():
            data[name] = make_wave(vpp)

        return pd.DataFrame(data)