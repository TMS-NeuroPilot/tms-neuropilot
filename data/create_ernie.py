#!/usr/bin/env python
import os
import pynibs
import numpy as np
from inspect import getsourcefile

subject_folder = os.path.split(os.path.abspath(getsourcefile(lambda: 0)))[0]

# subject information
########################################################################################################################
subject_id = 'ernie'
fn_subject_obj = subject_folder + f'{os.sep}{subject_id}.hdf5'

# MRI information
########################################################################################################################
mri = [dict()]
# T1/T2 from the local data copy; no DTI available locally (conductivity
# tensors are skipped, the mesh was created with scalar conductivity).
mri[0]['fn_mri_T1'] = os.path.join(subject_folder, subject_id, 'mri', 'T1.nii.gz')
mri[0]['fn_mri_T2'] = os.path.join(subject_folder, subject_id, 'mri', 'T2_reg.nii.gz')
mri[0]['fn_mri_DTI'] = ''
mri[0]['fn_mri_DTI_rev'] = ''
mri[0]['fn_mri_DTI_bvec'] = ''
mri[0]['fn_mri_DTI_bval'] = ''
mri[0]['dti_readout_time'] = '0.0476258'
mri[0]['dti_phase_direction'] = '-y'

# Mesh information
########################################################################################################################
mesh = dict()
mesh['ernie'] = dict()
mesh['ernie']['info'] = 'charm (simnibs 4.5) with fs'
mesh['ernie']['approach'] = 'charm'
mesh['ernie']['mesh_folder'] = os.path.join(subject_folder, subject_id, 'mesh')
mesh['ernie']['vertex_density'] = None
mesh['ernie']['fn_mesh_msh'] = os.path.join(mesh['ernie']['mesh_folder'], f'm2m_{subject_id}', f'{subject_id}.msh')
mesh['ernie']['fn_mesh_hdf5'] = os.path.join(mesh['ernie']['mesh_folder'], f'm2m_{subject_id}', f'{subject_id}.hdf5')
mesh['ernie']['fn_tensor_vn'] = f'm2m_{subject_id}/DTI_coregT1_tensor.nii.gz'
mesh['ernie']['mri_idx'] = 0
mesh['ernie']['fn_mri_conform'] = f"m2m_{subject_id}/T1.nii.gz"
mesh['ernie']['fn_lh_wm'] = None
mesh['ernie']['fn_rh_wm'] = None
mesh['ernie']['fn_lh_gm'] = None
mesh['ernie']['fn_rh_gm'] = None
mesh['ernie']['fn_lh_gm_curv'] = None
mesh['ernie']['fn_rh_gm_curv'] = None
mesh['ernie']['fn_lh_midlayer'] = f'm2m_{subject_id}/surfaces/lh.central.gii'
mesh['ernie']['fn_rh_midlayer'] = f'm2m_{subject_id}/surfaces/rh.central.gii'
mesh['ernie']['smooth_skin'] = .8
mesh['ernie']['refinement_roi'] = None  # 'midlayer_m1s1pmd'
mesh['ernie']['refinemement_element_size'] = None  # .75


# ROI information (first index: mesh, second index: roi)
########################################################################################################################
roi = dict()
roi['ernie'] = dict()
roi['ernie']['midlayer_lh_rh'] = dict()
roi['ernie']['midlayer_lh_rh']['type'] = 'surface'
roi['ernie']['midlayer_lh_rh']['info'] = 'freesurfer lh + rh whole brain midlayer'
roi['ernie']['midlayer_lh_rh']['gm_surf_fname'] = [mesh['ernie']['fn_lh_gm'], mesh['ernie']['fn_rh_gm']]
roi['ernie']['midlayer_lh_rh']['wm_surf_fname'] = [mesh['ernie']['fn_lh_wm'], mesh['ernie']['fn_rh_wm']]
roi['ernie']['midlayer_lh_rh']['midlayer_surf_fname'] = [mesh['ernie']['fn_lh_midlayer'], mesh['ernie']['fn_rh_midlayer']]
roi['ernie']['midlayer_lh_rh']['refine'] = False
roi['ernie']['midlayer_lh_rh']['delta'] = 0.5
roi['ernie']['midlayer_lh_rh']['X_ROI'] = None
roi['ernie']['midlayer_lh_rh']['Y_ROI'] = None
roi['ernie']['midlayer_lh_rh']['Z_ROI'] = None
roi['ernie']['midlayer_lh_rh']['layer'] = 3
roi['ernie']['midlayer_lh_rh']['fn_mask'] = None
roi['ernie']['midlayer_lh_rh']['fn_mask_avg'] = None

roi['ernie']['midlayer_m1s1pmd'] = dict()
roi['ernie']['midlayer_m1s1pmd']['type'] = 'surface'
roi['ernie']['midlayer_m1s1pmd']['info'] = 'freesurfer M1 + S1 + PMD'
roi['ernie']['midlayer_m1s1pmd']['gm_surf_fname'] = mesh['ernie']['fn_lh_gm']
roi['ernie']['midlayer_m1s1pmd']['wm_surf_fname'] = mesh['ernie']['fn_lh_wm']
roi['ernie']['midlayer_m1s1pmd']['midlayer_surf_fname'] = mesh['ernie']['fn_lh_midlayer']
roi['ernie']['midlayer_m1s1pmd']['refine'] = False
roi['ernie']['midlayer_m1s1pmd']['delta'] = 0.5
roi['ernie']['midlayer_m1s1pmd']['X_ROI'] = None
roi['ernie']['midlayer_m1s1pmd']['Y_ROI'] = None
roi['ernie']['midlayer_m1s1pmd']['Z_ROI'] = None
roi['ernie']['midlayer_m1s1pmd']['layer'] = 3
roi['ernie']['midlayer_m1s1pmd']['fn_mask'] = f"roi/midlayer_m1s1pmd/mask_{subject_id}_lh_m1pmdss.mgh"
roi['ernie']['midlayer_m1s1pmd']['fn_mask_avg'] = '/data/pt_01756/masks/lefthandknob_M1S1PMd.overlay'
roi['ernie']['midlayer_m1s1pmd']['hemisphere'] = "lh"

roi['ernie']['midlayer_lh_m1_BA4'] = dict()
roi['ernie']['midlayer_lh_m1_BA4']['type'] = 'surface'
roi['ernie']['midlayer_lh_m1_BA4']['info'] = 'freesurfer M1'
roi['ernie']['midlayer_lh_m1_BA4']['gm_surf_fname'] = mesh['ernie']['fn_lh_gm']
roi['ernie']['midlayer_lh_m1_BA4']['wm_surf_fname'] = mesh['ernie']['fn_lh_wm']
roi['ernie']['midlayer_lh_m1_BA4']['midlayer_surf_fname'] = mesh['ernie']['fn_lh_midlayer']
roi['ernie']['midlayer_lh_m1_BA4']['refine'] = False
roi['ernie']['midlayer_lh_m1_BA4']['delta'] = 0.5
roi['ernie']['midlayer_lh_m1_BA4']['X_ROI'] = None
roi['ernie']['midlayer_lh_m1_BA4']['Y_ROI'] = None
roi['ernie']['midlayer_lh_m1_BA4']['Z_ROI'] = None
roi['ernie']['midlayer_lh_m1_BA4']['layer'] = 3
roi['ernie']['midlayer_lh_m1_BA4']['fn_mask'] = f"roi/midlayer_lh_m1_BA4/mask_{subject_id}_lh_m1_BA4.mgh"
roi['ernie']['midlayer_lh_m1_BA4']['fn_mask_avg'] = '/data/pt_01756/masks/lefthandknob_M1.overlay'
roi['ernie']['midlayer_lh_m1_BA4']['hemisphere'] = "lh"

roi['ernie']['midlayer_lh_hippocampus_BA36'] = dict()
roi['ernie']['midlayer_lh_hippocampus_BA36']['type'] = 'surface'
roi['ernie']['midlayer_lh_hippocampus_BA36']['info'] = 'freesurfer lh_hippocampus_BA36'
roi['ernie']['midlayer_lh_hippocampus_BA36']['gm_surf_fname'] = mesh['ernie']['fn_lh_gm']
roi['ernie']['midlayer_lh_hippocampus_BA36']['wm_surf_fname'] = mesh['ernie']['fn_lh_wm']
roi['ernie']['midlayer_lh_hippocampus_BA36']['midlayer_surf_fname'] = mesh['ernie']['fn_lh_midlayer']
roi['ernie']['midlayer_lh_hippocampus_BA36']['refine'] = False
roi['ernie']['midlayer_lh_hippocampus_BA36']['delta'] = 0.5
roi['ernie']['midlayer_lh_hippocampus_BA36']['X_ROI'] = None
roi['ernie']['midlayer_lh_hippocampus_BA36']['Y_ROI'] = None
roi['ernie']['midlayer_lh_hippocampus_BA36']['Z_ROI'] = None
roi['ernie']['midlayer_lh_hippocampus_BA36']['layer'] = 3
roi['ernie']['midlayer_lh_hippocampus_BA36']['fn_mask'] = f"roi/midlayer_lh_hippocampus_BA36/mask_{subject_id}_lh_hippocampus_BA36.mgh"
roi['ernie']['midlayer_lh_hippocampus_BA36']['fn_mask_avg'] = '/data/pt_01756/masks/lh_hippocampus_BA36.overlay'
roi['ernie']['midlayer_lh_hippocampus_BA36']['hemisphere'] = "lh"

roi['ernie']['midlayer_rh_hippocampus_BA36'] = dict()
roi['ernie']['midlayer_rh_hippocampus_BA36']['type'] = 'surface'
roi['ernie']['midlayer_rh_hippocampus_BA36']['info'] = 'freesurfer rh_hippocampus_BA36'
roi['ernie']['midlayer_rh_hippocampus_BA36']['gm_surf_fname'] = mesh['ernie']['fn_rh_gm']
roi['ernie']['midlayer_rh_hippocampus_BA36']['wm_surf_fname'] = mesh['ernie']['fn_rh_wm']
roi['ernie']['midlayer_rh_hippocampus_BA36']['midlayer_surf_fname'] = mesh['ernie']['fn_rh_midlayer']
roi['ernie']['midlayer_rh_hippocampus_BA36']['refine'] = False
roi['ernie']['midlayer_rh_hippocampus_BA36']['delta'] = 0.5
roi['ernie']['midlayer_rh_hippocampus_BA36']['X_ROI'] = None
roi['ernie']['midlayer_rh_hippocampus_BA36']['Y_ROI'] = None
roi['ernie']['midlayer_rh_hippocampus_BA36']['Z_ROI'] = None
roi['ernie']['midlayer_rh_hippocampus_BA36']['layer'] = 3
roi['ernie']['midlayer_rh_hippocampus_BA36']['fn_mask'] = f"roi/midlayer_rh_hippocampus_BA36/mask_{subject_id}_rh_hippocampus_BA36.mgh"
roi['ernie']['midlayer_rh_hippocampus_BA36']['fn_mask_avg'] = '/data/pt_01756/masks/rh_hippocampus_BA36.overlay'
roi['ernie']['midlayer_rh_hippocampus_BA36']['hemisphere'] = "rh"

roi['ernie']['midlayer_rh_prefrontal'] = dict()
roi['ernie']['midlayer_rh_prefrontal']['type'] = 'surface'
roi['ernie']['midlayer_rh_prefrontal']['info'] = 'freesurfer rh_prefrontal'
roi['ernie']['midlayer_rh_prefrontal']['gm_surf_fname'] = mesh['ernie']['fn_rh_gm']
roi['ernie']['midlayer_rh_prefrontal']['wm_surf_fname'] = mesh['ernie']['fn_rh_wm']
roi['ernie']['midlayer_rh_prefrontal']['midlayer_surf_fname'] = mesh['ernie']['fn_rh_midlayer']
roi['ernie']['midlayer_rh_prefrontal']['refine'] = False
roi['ernie']['midlayer_rh_prefrontal']['delta'] = 0.5
roi['ernie']['midlayer_rh_prefrontal']['X_ROI'] = None
roi['ernie']['midlayer_rh_prefrontal']['Y_ROI'] = None
roi['ernie']['midlayer_rh_prefrontal']['Z_ROI'] = None
roi['ernie']['midlayer_rh_prefrontal']['layer'] = 3
roi['ernie']['midlayer_rh_prefrontal']['fn_mask'] = f"roi/midlayer_rh_prefrontal/mask_{subject_id}_rh_prefrontal.mgh"
roi['ernie']['midlayer_rh_prefrontal']['fn_mask_avg'] = '/data/pt_01756/masks/rh_prefrontal_mask.overlay'
roi['ernie']['midlayer_rh_prefrontal']['hemisphere'] = "rh"

########################################################################################################################
exp = dict()
exp['coil_placements'] = dict()

# add plot settings
########################################################################################################################
ps = []

ps.append(pynibs.create_plot_settings_dict(plotfunction_type='surface_vector_plot'))
ps[0]['info'] = ' '
ps[0]['plot_function'] = 'surface_vector_plot'
ps[0]['fname_in'] = '..._data.xdmf'
ps[0]['fname_png'] = '...png'
ps[0]['png_resolution'] = 1.0
ps[0]['quantity'] = [' ']
ps[0]['vlabels'] = None
ps[0]['vscales'] = None
ps[0]['datarange'] = [None, None]
ps[0]['domain_label'] = 'tissue_type'
ps[0]['domain_IDs'] = 0
ps[0]['colorbar_label'] = ' '
ps[0]['colorbar_position'] = [0.45, -0.05]
ps[0]['colorbar_orientation'] = 'Horizontal'
ps[0]['colorbar_aspectratio'] = 20
ps[0]['colorbar_titlefontsize'] = 12
ps[0]['colorbar_labelfontsize'] = 12
ps[0]['colorbar_labelformat'] = '%-#6.1f'
ps[0]['colorbar_numberoflabels'] = 5
ps[0]['colorbar_labelcolor'] = [0, 0, 0]
ps[0]['view'] = [[-332.040630013204, -16.8948837495393, 256.721941018442],
                 [-35.3111635316966, -13.6999528376981, 36.4196465112876],
                 [0.588834647614276, -0.167617710066906, 0.790682022712606],
                 [30, 0, 0]]
ps[0]['interpolate'] = True
ps[0]['edges'] = False
ps[0]['axes'] = False
ps[0]['colormap'] = 'Rainbow Blended White'
ps[0]['opacitymap'] = None
ps[0]['vscale_mode'] = ['off']
ps[0]['vector_mode'] = {'Every Nth Point': 10}
ps[0]['vcolor'] = None
ps[0]['background_color'] = np.array([1, 1, 1])
ps[0]['viewsize'] = np.array([1000, 1000])

# save subject information in .hdf5 file
########################################################################################################################
pynibs.save_subject_hdf5(fname=fn_subject_obj,
                          mri_dict=mri,
                          mesh_dict=mesh,
                          roi_dict=roi,
                          exp_dict=exp,
                          ps_dict=ps,
                          subject_id=subject_id,
                          subject_folder=subject_folder)

print(f'Created subject .hdf5 file: {fn_subject_obj}')
