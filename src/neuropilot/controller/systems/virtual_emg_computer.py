import asyncio
import numpy as np
import pandas as pd
from scipy.stats import multivariate_normal, norm, genextreme
from ..systems.system import System, SystemStatus
from collections import deque

#--- class VirtualEMGComputer(System) ---#
#A virtual EMG computer that simulates Motor Evoked Potential (MEP) responses for multiple muscles based on TMS coil placement,
#orientation, and stimulator output. It models spatial and recruitment biology using published statistical distributions
#(Goetz 2019, Farahmandrad & Goetz 2025).

class VirtualEMGComputer(System):
    NAME = "Virtual EMG Computer"
    DESCRIPTION = "Simulated"

    ERROR_RECOVERIES = {}

    def __init__(self, update_control_panel_func=None):
        super().__init__(update_control_panel_func=update_control_panel_func)

        """
            Initializes the VirtualEMGComputer with default coil state and builds
            a biologically parameterized muscle profile for each simulated muscle channel
            by sampling recruitment and spatial parameters from published distributions.

            Parameters
            ----------
            update_control_panel_func : callable, optional
                A callback function passed to the parent System class, used to update
                the control panel UI when the system status changes.
            """

        self.current_coil_x = 0.0
        self.current_coil_y = 0.0
        self.current_coil_theta = 0.0
        self.current_stimulator_output = 0.5

        # ONLY define the absolute ground-truth coordinates here
        self.muscles = {
            "ADC 0": {"hotspot_x": -60.0, "hotspot_y": -15.0},
            "ADC 1": {"hotspot_x": -68.0, "hotspot_y": -10.0},
            "ADC 2": {"hotspot_x": -48.0, "hotspot_y": -18.0}
        }

        # Dynamically build the rest of the biological profile strictly from published data
        for name in self.muscles.keys():
            recruitment_params = self._sample_recruitment_params()
            spatial_params = self._sample_spatial_params()

            self.muscles[name].update(recruitment_params)
            self.muscles[name].update(spatial_params)

    def _sample_recruitment_params(self):
        """
        Samples p1-p5 from the true population statistics (Goetz 2019, Eqs 2-4).
        Note: The paper provides variance (\sigma^2), so we must take the square root for numpy.

         Returns
    -------
    dict
        A dictionary with keys 'p1', 'p2', 'p3', 'p4', 'p5', each mapping
        to a float representing a sampled recruitment curve parameter.
        """
        # Eq 2: p1 ~ N(-5.0818, 3.5705e-3)
        p1 = np.random.normal(-5.0818, np.sqrt(3.5705e-3))

        # Eq 3: p2 ~ N(4.5323, 0.12617)
        p2 = np.random.normal(4.5323, np.sqrt(0.12617))

        # Eq 4: p3, p4, p5 (Multivariate Lognormal base 10)
        mu_log = np.array([3.6466, 0.42639, 1.6665])
        cov_log = np.array([
            [7.2027, 0.56974, -0.19746],
            [0.56974, 4.7426e-2, -1.5113e-2],
            [-0.19746, -1.5113e-2, 7.1071e-3]
        ])

        sampled_log = np.random.multivariate_normal(mu_log, cov_log)
        p3, p4, p5 = 10 ** sampled_log

        return {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5}

    def _sample_spatial_params(self):
        """
            Samples spatial and orientation parameters for a muscle's MEP response
            from the distributions defined in Farahmandrad & Goetz 2025, using the
            Posterior-Anterior (PA) coil orientation model.
            Note: The spatial covariance matrix (sigma_cov) is not provided in the
            paper and is filled with dummy uniform random values to prevent crashes.

            Returns
            -------
            dict
                A dictionary containing the following keys:
                - 'FL_min' : float — minimum location factor
                - 'FL_max' : float — maximum location factor
                - 'mu' : np.ndarray of shape (2,) — mean spatial position of the hotspot
                - 'sigma_cov' : np.ndarray of shape (2, 2) — spatial covariance matrix (dummy values)
                - 'gamma' : float — skew-normal mixture weight
                - 'alpha_prime' : np.ndarray of shape (2,) — skewness vector [alpha_1, alpha_2]
                - 'FO_min' : float — minimum orientation factor
                - 'FO_max' : float — maximum orientation factor
                - 'sigma_orient' : float — orientation sensitivity parameter
                - 'theta_0' : float — baseline optimal coil angle (degrees)
                - 'theta_NI' : float — natural inclination angle offset (degrees)
        """
        # Eq 2 & 3: Skewness (alpha)
        alpha_1 = np.random.normal(-2.50, np.sqrt(1.17))
        alpha_2 = np.random.normal(2.23, np.sqrt(1.27))

        # Eq 4: Gamma
        gamma = np.random.normal(0.100, np.sqrt(3.17e-2))

        # Eq 5 & 6: Location Factors
        FL_max = np.random.normal(0.982, np.sqrt(1.33e-4))
        FL_min = np.random.normal(0.518, np.sqrt(8.50e-3))

        # Eq 9, 10, 12: Orientation (PA)
        theta_0_PA = np.random.normal(39.1, np.sqrt(68.1))
        theta_NI = np.random.normal(21.5, np.sqrt(169))
        sigma_PA = np.random.normal(0.132, np.sqrt(1.00e-3))

        # Eq 14: Max Orientation
        FO_max_PA = np.random.normal(0.827, np.sqrt(1.04e-2))

        # Eq 15: Min Orientation (Using AP values because PA is omitted in text)
        FO_min_PA = np.random.normal(0.569, np.sqrt(4.40e-3))

        # --- MISSING FROM PAPER: Covariance Matrix ---
        # The paper does not provide the statistics for the spatial spread (Sigma).
        # We must use dummy logic here so the simulation doesn't crash.
        var_x = np.random.uniform(100.0, 400.0)
        var_y = np.random.uniform(100.0, 400.0)
        cov_xy = np.random.uniform(-10.0, 10.0)

        return {
            "FL_min": FL_min,
            "FL_max": FL_max,
            "mu": np.array([-60, -15.0]),
            "sigma_cov": np.array([[var_x, cov_xy], [cov_xy, var_y]]),  # <--- DUMMY
            "gamma": gamma,
            "alpha_prime": np.array([alpha_1, alpha_2]),
            "FO_min": FO_min_PA,
            "FO_max": FO_max_PA,
            "sigma_orient": sigma_PA,
            "theta_0": theta_0_PA,
            "theta_NI": theta_NI
        }

    # --- System Connections (Mocked) ---
    def try_connect(self):
        """
            Mocked connection method. Sets the system status to OK without
            performing any real hardware connection.
        """
        super().set_system_status(SystemStatus.OK)

    def recover(self, recovery):
        """
            Attempts to recover the system from an error state by calling try_connect.

            Parameters
            ----------
            recovery : any
                The recovery action descriptor (unused in this implementation).
        """
        self.try_connect()

    async def check_system(self):
        """
            Asynchronously checks and updates the system status. If a pending recovery
            is queued, it dequeues one entry and sets the system status to OK.
        """
        if hasattr(self, 'recovery_queue') and self.recovery_queue:
            self.recovery_queue.popleft()
        super().set_system_status(SystemStatus.OK)

    def set_current_state(self, x, y, theta, stim_output=1):
        """
        Updates the current coil position and stimulator output used for the
        next MEP computation. Note: coil angle (theta) is currently hardcoded
        to 45 degrees internally regardless of the passed value.

        Parameters
        ----------
        x : float
            X position of the coil in SimNIBS coordinate space (mm).
        y : float
            Y position of the coil in SimNIBS coordinate space (mm).
        theta : float
            Intended coil orientation angle (degrees). Currently ignored —
            internal theta is hardcoded to 45.
        stim_output : float, default: 1
            Normalized stimulator output intensity [0 ... 1].
          """
        self.current_coil_x = x
        self.current_coil_y = y
        self.current_coil_theta = 45
        self.current_stimulator_output = stim_output
        print("HERREEEEEEEEEEEEEE", self.current_coil_x, self.current_coil_y, theta, self.current_stimulator_output)

    def get_latest_emg_df(self, idx=None):
        """
            Computes a simulated EMG response for each muscle channel based on the
            current coil state. Applies the full Goetz 2019 model including location
            factor (F_L), orientation factor (F_O), recruitment curve, and
            trial-to-trial noise. The resulting Vpp values are capped at 3× the
            biological expected maximum to allow realistic noise while preventing
            unrealistic outliers.

            Parameters
            ----------
            idx : any, optional
                Unused parameter, reserved for potential future indexing.

            Returns
            -------
            pd.DataFrame
                A DataFrame returned by `_generate_polyphasic_emg` containing
                time-series EMG waveforms for all three muscle channels
                ('ADC 0', 'ADC 1', 'ADC 2').
        """
        vpps = {}
        for name, params in self.muscles.items():
            pos = np.array([self.current_coil_x, self.current_coil_y])

            # Location Factor (F_L)
            phi_k = multivariate_normal.pdf(pos, mean=params["mu"], cov=params["sigma_cov"])
            skew_val = np.dot(params["alpha_prime"], pos)
            Phi = norm.cdf(skew_val)

            FL_base = (2 / (2 + params["gamma"])) * phi_k * (1 + params["gamma"] * Phi)
            FL_normalized = min(FL_base * 1000, 1.0)
            FL = params["FL_min"] + (params["FL_max"] - params["FL_min"]) * FL_normalized

            # Orientation Factor (F_O)
            exp_term = np.exp(
                -params["sigma_orient"] * (self.current_coil_theta - params["theta_0"] - params["theta_NI"]))
            FO = params["FO_min"] + (params["FO_max"] - params["FO_min"]) * (1 / (1 + exp_term))

            s_tilde = self.current_stimulator_output * FL * FO

            # --- Trial-to-Trial Noise from Goetz 2019 ---
            # Eq 7: e_yadd uses Generalized Extreme Value distribution
            # SciPy's shape param 'c' is the negative of Goetz's 'k'.

            e_yadd = genextreme.rvs(c=-0.39316, loc=10 ** params["p1"], scale=1.4739e-6)

            # Eq 5: e_ymult ~ LogNormal base 10
            e_ymult_log = np.random.normal(-0.9645334, np.sqrt(2.2759e-2))
            e_ymult = 10 ** e_ymult_log

            # Eq 6: e_xadd ~ LogNormal base 10
            e_xadd_log = np.random.normal(0.68827324, np.sqrt(2.3671e-2))
            e_xadd = 10 ** e_xadd_log

            # Recruitment Curve Eq 1
            # CORRECT:
            inner = (params["p3"] / max(s_tilde - params["p5"] + e_xadd, 1e-9)) ** params["p4"]
            fraction = params["p2"] / (1 + inner)

            # Final Vpp (Equation 1, Goetz 2019)
            Vpp = e_yadd + np.exp(np.log(10) * (e_ymult - 7 + fraction))
            # Calculate the true biological expected max plateau in Volts (approx 10^(-7 + p2))
            expected_max_volts = 10 ** (-7 + params["p2"])

            # Cap Vpp safely at 3x the expected max to allow for realistic noise spikes
            vpps[name] = max(min(Vpp, expected_max_volts * 3.0), 0.0)*1000
            print(vpps)

        return self._generate_polyphasic_emg(vpps["ADC 0"], vpps["ADC 1"], vpps["ADC 2"])

    def _generate_polyphasic_emg(self, vpp_a, vpp_b, vpp_c, duration=0.7, sample_rate=4000):
        """
            Generates synthetic polyphasic EMG waveforms for three muscle channels
            using a Gaussian-enveloped sine wave model with additive Gaussian noise.

            Parameters
            ----------
            vpp_a : float
                Peak-to-peak amplitude (Volts) for channel ADC 0.
            vpp_b : float
                Peak-to-peak amplitude (Volts) for channel ADC 1.
            vpp_c : float
                Peak-to-peak amplitude (Volts) for channel ADC 2.
            duration : float, default: 0.7
                Total duration of the simulated EMG signal in seconds.
            sample_rate : int, default: 4000
                Sampling rate in Hz.

            Returns
            -------
            pd.DataFrame
                A DataFrame with columns 'Time', 'ADC 0', 'ADC 1', 'ADC 2',
                where each ADC column contains the simulated voltage waveform
                over the specified duration.
            """
        t = np.linspace(0, duration, int(duration * sample_rate))

        def make_wave(vpp):
            center = 0.525
            width = 0.005
            freq = 150
            env = np.exp(-((t - center) ** 2) / (2 * width ** 2))
            wave = np.sin(2 * np.pi * freq * t) * env
            return (wave * (vpp / 2.0)) + np.random.normal(0, 0.001, len(t))

        df = pd.DataFrame({
            "Time": t,
            "ADC 0": make_wave(vpp_a),
            "ADC 1": make_wave(vpp_b),
            "ADC 2": make_wave(vpp_c)
        })

        return df