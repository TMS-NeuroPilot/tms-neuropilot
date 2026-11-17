
import os

import numpy as np
import pandas as pd
from scipy.stats import genextreme
from pynibs.expio.Mep import get_mep_virtual_subject_DVS

from ..systems.system import System, SystemStatus


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


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
        # them in .env and restart the controller.
        self.model = (os.getenv("VIRTUAL_MEP_MODEL", "dvs").strip().lower()
                      or "dvs")
        if self.model not in {"dvs", "tvs"}:
            print(f"[WARN] Unknown VIRTUAL_MEP_MODEL={self.model!r}; using dvs.")
            self.model = "dvs"
        self.noise_mv = _env_float("VIRTUAL_MEP_NOISE_MV", 0.001)
        self.trial_variability = _env_bool("VIRTUAL_MEP_TRIAL_VARIABILITY", True)
        self.mt = _env_float("VIRTUAL_MEP_MT", 60.0)
        self.upper_limit = _env_float("VIRTUAL_MEP_UPPER_LIMIT", 100.0)
        self.efield_scale = _env_float("VIRTUAL_MEP_EFIELD_SCALE", 1.4)

        # DVS parameters are in the E-field domain (V/m), except the output
        # amplitude/offset and the output-side log-noise.
        self.dvs_x0 = _env_float("VIRTUAL_MEP_DVS_X0", 75.0)
        self.dvs_r = _env_float("VIRTUAL_MEP_DVS_R", 0.10)
        self.dvs_sigma_x = _env_float("VIRTUAL_MEP_DVS_SIGMA_X", 5.0)
        self.dvs_amp = _env_float("VIRTUAL_MEP_DVS_AMP", 1.0)
        self.dvs_y0 = _env_float("VIRTUAL_MEP_DVS_Y0", 0.01)
        self.dvs_sigma_y = _env_float("VIRTUAL_MEP_DVS_SIGMA_Y", 0.10)

        # TVS parameters in the original model's convention. p3-p7 are the
        # linear values (the paper reports their log10 means).
        self.tvs_p1 = _env_float("VIRTUAL_MEP_TVS_P1", -5.0818)
        self.tvs_p2 = _env_float("VIRTUAL_MEP_TVS_P2", -2.4677)
        self.tvs_p3 = _env_float("VIRTUAL_MEP_TVS_P3", 4430.0)
        self.tvs_p4 = _env_float("VIRTUAL_MEP_TVS_P4", 2.67)
        self.tvs_p5 = _env_float("VIRTUAL_MEP_TVS_P5", 46.3)
        self.tvs_p6 = _env_float("VIRTUAL_MEP_TVS_P6", 0.1086)
        self.tvs_p7 = _env_float("VIRTUAL_MEP_TVS_P7", 4.88)
        self.tvs_p8 = _env_float("VIRTUAL_MEP_TVS_P8", 1.4739e-6)
        self.tvs_p9 = _env_float("VIRTUAL_MEP_TVS_P9", 0.39316)

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
            "Model": self.model.upper(),
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

    def set_current_state(self, coil_placement_idx, stimuator_amplitude):
        self.current_coil_placement_idx = coil_placement_idx
        self.stimulator_amplitude = stimuator_amplitude

    def _normalise_field(self, e_field):
        """Return the TVS input as a fraction of maximum stimulator output.

        The TVS model expects its amplitude in [0, 1] of MSO; its own
        threshold is around the middle of that range.  Mapping the configured
        motor threshold to zero (the old ``scale_e_for_dvs`` behaviour)
        compressed 60–100 V/m into the model's flat sub-threshold part, so a
        field in the configured range produced no useful MEP.
        """
        if e_field <= self.mt or self.upper_limit <= 0:
            return 0.0
        return float(np.clip(e_field / self.upper_limit, 0.0, 1.0))

    def _dvs_mep(self, e_field):
        """DVS response for one E-field value in V/m."""
        if (e_field <= self.mt or self.dvs_r <= 0
                or self.dvs_amp <= 0):
            return 0.0
        sigma_x = self.dvs_sigma_x if self.trial_variability else 0.0
        sigma_y = self.dvs_sigma_y if self.trial_variability else 0.0
        mep = get_mep_virtual_subject_DVS(
            np.array([float(e_field)]),
            x0=self.dvs_x0,
            r=self.dvs_r,
            amp=self.dvs_amp,
            y0=self.dvs_y0,
            sigma_x=sigma_x,
            sigma_y=sigma_y,
        )
        return max(float(np.asarray(mep).reshape(-1)[0]), 0.0)

    def _tvs_mep(self, x):
        """TVS response for a normalised MSO input in [0, 1]."""
        if (x <= 0 or self.tvs_p3 <= 0 or self.tvs_p4 <= 0
                or self.tvs_p8 <= 0):
            return 0.0

        # Original Goetz/MATLAB parameterisation: p1/p2 are log10 terms;
        # p3-p7 are linear coefficients/standard deviations.
        p1, p2, p3, p4, p5 = (self.tvs_p1, self.tvs_p2, self.tvs_p3,
                              self.tvs_p4, self.tvs_p5)
        p6, p7, p8, p9 = (self.tvs_p6, self.tvs_p7,
                          self.tvs_p8, self.tvs_p9)
        noise_x = np.random.normal(0.0, p7) if self.trial_variability else 0.0
        noise_y = np.random.normal(0.0, p6) if self.trial_variability else 0.0
        x_prime = max(2.224e-16, x * 100.0 - p5 + noise_x)
        if self.trial_variability:
            add_y = float(genextreme.rvs(
                -p9, loc=10 ** p1, scale=p8, size=1)[0])
        else:
            add_y = 10 ** p1
        denominator = 1.0 + p3 / x_prime ** p4
        mep_v = add_y + 10 ** (noise_y - 7.0 + (p2 + 7.0) / denominator)
        return max(float(mep_v) * 1000.0, 0.0)

    def _mep_for_field(self, e_field):
        """Return ``(MEP in mV, TVS x)`` for the configured model."""
        if e_field <= self.mt:
            return 0.0, 0.0
        if self.model == "dvs":
            return self._dvs_mep(e_field), None
        x = self._normalise_field(e_field)
        return self._tvs_mep(x), x

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
        for channel_index, (name, elem_idx) in enumerate(
                zip(self.data_channel_names, self.channel_elements)):
            # Both models use the field at that channel's configured MEP
            # source element, either from the precomputed row or the online
            # per-pulse field.
            if e_field_for_mep is not None:
                e_field = e_field_for_mep[elem_idx]
            else:
                e_field = (
                    self.e_matrix[self.current_coil_placement_idx, elem_idx]
                    * self.efield_scale
                    * self.stimulator_amplitude
                )

            vpp, e_normalized = self._mep_for_field(e_field)
            vpps[name] = vpp
            label = (self.display_names[channel_index]
                     if channel_index < len(self.display_names) else name)
            if self.model == "tvs":
                print(f"Virtual EMG {label} [TVS]: E={float(e_field):.2f} V/m, "
                      f"x={float(e_normalized):.2f}, MEP={vpp:.2f} mV",
                      flush=True)
            else:
                print(f"Virtual EMG {label} [DVS]: E={float(e_field):.2f} V/m, "
                      f"MEP={vpp:.2f} mV", flush=True)

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