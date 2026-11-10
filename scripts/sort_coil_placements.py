import pynibs
import h5py
import glob
import numpy as np
import os

folder_opt_id = "/data/pt_01756/probands/30298.bb/opt/prestudy_hugh/coil_seq"
hdf5_in = "/data/pt_01756/probands/30298.bb/opt/prestudy_hugh/coil_positions_for_paraview_hugh.hdf5"
hdf5_out = hdf5_in.replace('.hdf5', 'sorted.hdf5')

opt_fns = glob.glob(f"{folder_opt_id}/*.txt")

with h5py.File(hdf5_in, 'r') as f:
    matsimnibs = f['matsimnibs'][:]


for opt_fn in opt_fns:
    print(opt_fn)
    opt_in = np.loadtxt(opt_fn).astype(int)

    suf = os.path.split(opt_fn)[1].replace('.txt','')

    hdf5_out =  f'/data/pt_01756/probands/30298.bb/opt/prestudy_hugh/sorted/sorted_{suf}.hdf5'

    mats_opt, cost, route, cost_org = pynibs.coil.opt_coil_placement_order(matsimnibs, hdf5_out, w_pos=2, w_ang=1,

                                                                                 opt_indices=opt_in)
    route = opt_in[np.array(route)]
    print(f"Cost_org: {np.round(cost_org, 2)}, cost opt: {np.round(cost, 2)}")
    np.savetxt(f"/data/pt_01756/probands/30298.bb/opt/prestudy_hugh/sorted/sorted_{suf}.txt", np.array(route).astype(int), fmt='%i',)


