import csv
import h5py
import pandas as pd
import pynibs
import numpy as np

fn_e = "/data/pt_01756/studies/cobot_2ndtry/ernie_roi/e_scaled.hdf5"
folder = "/E_mag"
idx_chan1 = 13227
idx_chan2 = 2997
idx_chan3 = 9085

results_folder = "/data/pt_01756/studies/cobot_2ndtry/ernie_roi/emg_fake/"

with h5py.File(fn_e, 'r') as f:
    e_chan1 = f['E_mag'][:][:,idx_chan1]
    e_chan2 = f['E_mag'][:][:,idx_chan2]
    e_chan3 = f['E_mag'][:][:,idx_chan3]


e_chan1 /= e_chan1.max()
e_chan2 /= e_chan2.max()
e_chan3 /= e_chan3.max()

meps_chan1 = pynibs.expio.get_mep_virtual_subject_DVS(e_chan1, x0=0.5, r=10, amp=1, sigma_x=0, sigma_y=0, y0=1e-2, seed=None, rng=None)
meps_chan2 = pynibs.expio.get_mep_virtual_subject_DVS(e_chan2, x0=0.5, r=10, amp=1, sigma_x=0, sigma_y=0, y0=1e-2, seed=None, rng=None)
meps_chan3 = pynibs.expio.get_mep_virtual_subject_DVS(e_chan3, x0=0.5, r=10, amp=1, sigma_x=0, sigma_y=0, y0=1e-2, seed=None, rng=None)

n_samples = 2000
sampling_rate = 4000

time = np.linspace(0,0.5,n_samples)
tms_pulse_time=.2
start_mep=20
end_mep=35
start = int(tms_pulse_time * sampling_rate + start_mep * sampling_rate / 1000)
end = int(tms_pulse_time * sampling_rate + end_mep * sampling_rate / 1000)
mid = int((end - start) / 2) + start
for i in range(e_chan1.shape[0]):
    emg_1 = np.zeros((n_samples))

    emg_1[start:mid] = e_chan1[i] * 10
    emg_1[mid:end] = -e_chan1[i] * 10

    emg_2 = np.zeros((n_samples))

    emg_2[start:mid] = e_chan2[i] * 10
    emg_2[mid:end] = -e_chan2[i] * 10

    emg_3 = np.zeros((n_samples))

    emg_3[start:mid] = e_chan3[i] * 10
    emg_3[mid:end] = -e_chan3[i] * 10

    res = {
        "\"s\"":time,
        "\"ADC 0\"": emg_1,
        "\"ADC 1\"": emg_2,
        "\"ADC 2\"": emg_3,
           }
    pd.DataFrame().from_dict(res).to_csv(f"{results_folder}/signal_emg_out_{i:0>4}.txt",
                                         index=False, sep="\t",quoting=csv.QUOTE_NONE)