#!/usr/bin/env python3
"""Create a FEM head model (mesh) from MRI data with SimNIBS charm.

Runs the full head-modeling chain for a pynibs subject: segmentation and
meshing with ``charm`` (optionally seeded by a FreeSurfer reconstruction),
conversion to the subject ``*.hdf5`` mesh, ROI surface handling, spherical
mesh refinement, skin smoothing, degenerate-element repair, and anisotropic
conductivity tensors from DWI (``dwi2cond``). Everything is driven by the
subject object (``--fn_subject``): the ``mri`` entries supply T1/T2/DTI
paths, the ``mesh`` entry supplies folders, approach and refinement settings.

Requires the SimNIBS command-line tools (``charm``, ``dwi2cond``,
``meshmesh``) on the PATH and, for fsaverage-based ROIs, a FreeSurfer
environment (``SUBJECTS_DIR``).

Example:
    python scripts/01_create_head_model.py \
        -s data/ernie/ernie.hdf5 \
        -m mesh_ernie_lincc --charm_ini scripts/configs/charm_410.ini
"""

import os
import sys
import time
import h5py
import shutil
import pynibs
import simnibs
import warnings
import argparse
import datetime
import numpy as np
import nibabel as nib

# Live progress output even when stdout is redirected to a file (Python
# block-buffers by default, which hides prints for hours on long runs).
sys.stdout.reconfigure(line_buffering=True)

from simnibs import __version__ as sim_v
from pynibs.util.simnibs_io import smooth_mesh

# Get command line arguments
parser = argparse.ArgumentParser(description='Creates a FEM mesh from MRI data')
parser.add_argument('-s', '--fn_subject', help='Path to *.hdf5-file of subject', required=True)
parser.add_argument('--charm_ini', help='charm.ini file to use.',
                    default=f"{os.path.dirname(os.path.realpath(__file__))}/configs/charm_410.ini")
parser.add_argument('-m', '--mesh_idx', help='The mesh name from subject object', required=True)
parser.add_argument('-l', '--layer', help='Create cortical layer', action='store_true', required=False,
                    default=False)
parser.add_argument('--charm_cmd_params', help='Additional parameters to charm, e.g. forcerun or mesh',
                    required=False,
                    default='')
parser.add_argument('--mesh', help='Skip segmentation and only mesh headmodel', action='store_true',
                    required=False,
                    default=False)
parser.add_argument('--debug', help='Run charm in debug mode saving additional intermediate output',
                    action='store_true', required=False, default=False)

args = parser.parse_args()
charm_cmdline = "charm"
dwi2cond_cmdline = "dwi2cond"
if os.system(f"which {dwi2cond_cmdline}") == 256:
    simnibs_dir = os.path.split(simnibs.__file__)[0]
    dwi2cond_cmdline = f"{simnibs_dir}/external/dwi2cond"
    assert os.system(f"which {dwi2cond_cmdline}") == 0, f"Cannot find dwi2cond executable."
meshmesh_cmdline = "meshmesh"
layer = args.layer
mesh_only = args.mesh

debug_flag = ""
if args.debug:
    debug_flag = "--debug"


def logprint(text):
    """Just a wrapper to print and write text to a logfile."""
    with open(log_file, "a") as logfile:
        logfile.write(f'{text}\n')
    print(text)


fn_subject = os.path.abspath(args.fn_subject)
subject = pynibs.load_subject(fn_subject)
mesh_idx = args.mesh_idx
charm_ini_fn = args.charm_ini

assert mesh_idx in subject.mesh, f"Mesh '{mesh_idx}' not found in {args.fn_subject}"
mesh_folder = subject.mesh[mesh_idx]["mesh_folder"]
log_file = os.path.join(mesh_folder, f"info_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
charm_cmd_params = args.charm_cmd_params
if charm_cmd_params != '' and not charm_cmd_params.startswith('--'):
    charm_cmd_params = '--' + charm_cmd_params

try:
    use_fs = subject.mesh[mesh_idx]["use_fs"]
except KeyError:
    use_fs = False


def print_mesh_info(fn):
    logprint("- " * 32)
    logprint(f"Mesh information: {fn}")
    pref = os.path.basename(fn)
    with h5py.File(fn, 'r') as f:  # f = h5py.File(mesh_fn_smoothed_hdf5,'r')
        logprint(f"{pref}: total nodes: {f['/mesh/nodes/node_number'].shape[0]: >7}")
        logprint(f"{pref}: total elms: {f['/mesh/elm/elm_number'].shape[0]: >7}")
        logprint(f"{pref}: total tris: {np.sum(f['/mesh/elm/elm_type'][:] == 2): >7}")
        logprint(f"{pref}: total tets: {np.sum(f['/mesh/elm/elm_type'][:] == 4): >7}")
        logprint("- " * 32)
        for t in np.unique(f['/mesh/elm/tet_tissue_type']):
            logprint(f"{pref}: tet tissue type {t:0>4}: {np.sum(f['/mesh/elm/tet_tissue_type'] == t): >7}")
        logprint("- " * 32)
        for t in np.unique(f['/mesh/elm/tri_tissue_type']):
            logprint(f"{pref}: tri tissue type {t:0>4}: {np.sum(f['/mesh/elm/tri_tissue_type'] == t): >7}")
        logprint("- " * 32)


time_mesh = 0
time_roi = 0
time_dwi = 0

# logprint simulation info
# ================================================================================
os.makedirs(os.path.split(log_file)[0], exist_ok=True)
logprint("-" * 64)
logprint(f"{parser.description}")
args_dict = vars(args)
for key in args_dict.keys():
    logprint(f"{key: >15}: {args_dict[key]}")
logprint("-" * 64)

if charm_ini_fn:
    # this will always be appended to all charm, meshmesh calls
    charm_ini_fn = f" --usesettings={os.path.abspath(charm_ini_fn)}"
else:
    charm_ini_fn = ''

# load subject info
mesh_dict = subject.mesh[mesh_idx]
mri_idx = mesh_dict["mri_idx"]

# set approach specific options
approach = mesh_dict["approach"]

if approach == "charm":
    vertex_density = None
    numvertices = None
else:
    raise NotImplementedError(f"Approach {approach} not implemented. Use 'charm' or switch to other 'mri2msh' script")

# check if 'mri' field exists
if not hasattr(subject, 'mri'):
    logprint(f'\'MRI\' attribute missing in {fn_subject}. Quitting.')
    sys.exit(1)

mesh_folder = mesh_dict["mesh_folder"]
if not os.path.exists(mesh_folder):
    os.makedirs(mesh_folder)

t1_path = subject.mri[mri_idx]['fn_mri_T1']
t2_path = subject.mri[mri_idx]['fn_mri_T2']
bvec = subject.mri[mri_idx]['fn_mri_DTI_bvec']
bval = subject.mri[mri_idx]['fn_mri_DTI_bval']
dti_path = subject.mri[mri_idx]['fn_mri_DTI']
try:
    dti_tensor_path = subject.mri[mri_idx]['dti_tensor_fn']  # already prepared tensor file
except KeyError:
    dti_tensor_path = None

try:
    fsdir = subject.mri[mri_idx]['freesurfer_dir']
    if fsdir.endswith('/') or fsdir.endswith('\\'):
        fsdir = fsdir[:-1]
except (KeyError, AttributeError):
    fsdir = None

try:
    smooth_skin = mesh_dict['smooth_skin']
except KeyError:
    smooth_skin = False
if smooth_skin is None or smooth_skin == 0:
    smooth_skin = False
assert smooth_skin is False or 0 < smooth_skin <= 1, f"['smooth_skin'] has to be within [0,1] or None."

if 'fn_mri_DTI_rev' in subject.mri[mri_idx].keys():
    dti_rev_path = subject.mri[mri_idx]['fn_mri_DTI_rev']
else:
    dti_rev_path = ''
if dti_rev_path is None:
    dti_rev_path = ''

if t2_path is None:
    t2_path = ''

# check if FreeSurfer env is available
try:
    fsaverage_dir = os.path.join(f"{os.environ['SUBJECTS_DIR']}", "fsaverage")
except KeyError:
    warnings.warn("Freesurfer not found, some meshing functions won't work.")
    time.sleep(2)

if use_fs and fsdir is None:
    raise ValueError("use_fs is set to True but no FreeSurfer [fsdir] directory is provided.")

# create mesh from mri if not already done
#############################################################################################################
if use_fs:
    # FreeSurfer needs a subject ID so we'll use the subdirectory as the subject ID
    fsdir_tmp, sub_id_tmp = os.path.split(fsdir)
    if not os.path.exists(fsdir) or len(os.listdir(fsdir)) == 0:  # if directory does not exist or is empty
        fs_cmd = (f"recon-all "
                  f"-s {sub_id_tmp} "
                  f"-sd {fsdir_tmp} "
                  f"-i {subject.mri[mri_idx]['fn_mri_T1']} ")
        if subject.mri[mri_idx]['fn_mri_T2'] is not None:
            fs_cmd += f"-T2 {subject.mri[mri_idx]['fn_mri_T2']} "
        fs_cmd += " -all"
        logprint(f"Calling {fs_cmd}")

        # Execute the recon-all command
        ret = os.system(fs_cmd)
        if ret == 0:
            logprint(f"recon-all completed successfully for {subject.id}.")
        else:
            logprint(f"recon-all failed for {subject.id} with code {ret}.")
            quit(ret)
    else:
        logprint(f"Found FreeSurfer directory {fsdir}. Skipping FreeSurfer reconstruction.")

if approach != "charm":
    logprint(f"Choose approach='charm' in {fn_subject} or use different script for meshing")
    quit()

mesh_fn = mesh_dict["fn_mesh_msh"]
mesh_fn_hdf5 = mesh_dict['fn_mesh_hdf5']

mesh_fn_charm = os.path.join(mesh_folder, 'm2m_' + subject.id, subject.id + ".msh")

mesh_fn_org = mesh_fn.replace('.msh', '_org.msh')
mesh_fn_org_hdf5 = mesh_fn_org.replace('.msh', '.hdf5')

mesh_fn_refined = mesh_fn.replace(".msh", "_refined.msh")
mesh_fn_refined_hdf5 = mesh_fn_refined.replace(".msh", ".hdf5")

mesh_fn_smoothed = mesh_fn.replace('.msh', '_smoothed.msh')
mesh_fn_smoothed_hdf5 = mesh_fn_smoothed.replace('.msh', '.hdf5')

smooth_settings_fn = f"{mesh_folder}/m2m_{subject.id}/smooth_settings.ini"
refinement_nii_fn = f"{mesh_folder}/m2m_{subject.id}/refinement.nii.gz"
refinement_upsampled_nii_fn = f"{mesh_folder}/m2m_{subject.id}/refinement_upsampled.nii.gz"

mesh_fn_unfixed = mesh_fn.replace('.msh', '_unfixed.msh')

if not os.path.isfile(mesh_fn):
    # open logfile
    logprint(f"Started mri2msh_charm.py on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logprint("================================================")
    logprint(f"Subject object file: {fn_subject}")
    logprint(f"mri_idx:             {mri_idx}")
    logprint(f"mesh_idx:            {mesh_idx}")
    logprint(f"approach:            {approach}")
    logprint(f"use_fs:              {use_fs}")
    logprint(f"fs_dir:              {fsdir}")
    logprint(f"fn_mri_T1:           {subject.mri[mri_idx]['fn_mri_T1']}")
    logprint(f"fn_mri_T2:           {subject.mri[mri_idx]['fn_mri_T2']}")
    logprint(f"fn_mri_DTI_bvec:     {subject.mri[mri_idx]['fn_mri_DTI_bvec']}")
    logprint(f"fn_mri_DTI_bval:     {subject.mri[mri_idx]['fn_mri_DTI_bval']}")
    logprint(f"fn_mri_DTI:          {subject.mri[mri_idx]['fn_mri_DTI']}\n")

    # meshing -----------------------------------------------------------
    os.chdir(mesh_folder)
    logprint(f"Target folder: {mesh_folder}")

    if not mesh_only:
        # set qform to sform of T1 ------------------------------------------
        # some scanners may yield different q- and s-form, enforce s-form here for consistency
        img = nib.load(subject.mri[mri_idx]['fn_mri_T1'])
        affine, code = img.get_sform(coded=True)
        img.set_qform(affine=affine, code=code)
        fn_t1_ext = pynibs.expio.splitext_niigz(subject.mri[mri_idx]['fn_mri_T1'])
        subject.mri[mri_idx]['fn_mri_T1'] = fn_t1_ext[0] + "_qform" + fn_t1_ext[1]
        nib.save(img, subject.mri[mri_idx]['fn_mri_T1'])

        # coregister T2 to T1 -----------------------------------------------
        # additional coregistration step improves headmodels
        if len(t2_path) != 0:
            logprint(f"Coregistering T2 to T1 ...")
            cmd_charm = f"{charm_cmdline} {subject.id} {t1_path} {t2_path} " \
                        f"--registerT2 --forceqform --forcerun {debug_flag}"
            logprint(f"Calling {cmd_charm}")
            ret = os.system(cmd_charm)
            if ret == 0:
                logprint(f"Coregistering finished for {subject.id}.")
            else:
                logprint(f"Coregistering finished failed for {subject.id} with code {ret}")
                quit(ret)
            t1_path = f"{mesh_folder}/T1.nii.gz"
            t2_path = f"{mesh_folder}/T2_reg.nii.gz"
            os.rename(f"{mesh_folder}/m2m_{subject.id}/T1.nii.gz", t1_path)
            os.rename(f"{mesh_folder}/m2m_{subject.id}/T2_reg.nii.gz", t2_path)
            shutil.rmtree(f"{mesh_folder}/m2m_{subject.id}")

            # and now set the qform again
            img = nib.load(t1_path)
            img.header['qform_code'] = 1
            nib.save(img, t1_path)

            img = nib.load(t2_path)
            img.header['qform_code'] = 1
            nib.save(img, t2_path)

        # meshing -----------------------------------------------------------
        cmd_charm = f"{charm_cmdline} {subject.id} {t1_path} {t2_path} {charm_ini_fn} {charm_cmd_params} {debug_flag}"
    else:
        cmd_charm = f"{charm_cmdline} {subject.id} --mesh {debug_flag}"

    if use_fs:
        cmd_charm += f" --fs-dir {fsdir} "

    logprint(f"Meshing with cmd: {cmd_charm}")
    ret = os.system(cmd_charm)
    if ret == 0:
        logprint(f"Meshing finished for {subject.id}.")
    else:
        logprint(f"Meshing finished failed for {subject.id} with code {ret}")
        quit(ret)

    # check mesh for degenerated elements
    zero_tris, zero_tets, neg_tets = pynibs.util.simnibs_io.check_mesh(mesh_fn)
    if zero_tris.size or zero_tets.size or neg_tets.size:
        warnings.warn(f"Degenerated mesh {mesh_fn}: zero_tris: "
                      f"{zero_tris.size} zero tris, {zero_tets.size} zero_tets, {neg_tets.size} neg_tets left over.")
    # rename .msh file to user specific filename
    if mesh_fn_charm != mesh_fn:
        os.rename(mesh_fn_charm, mesh_fn)

    # create hdf5 for mesh
    logprint(f" > Writing file: {mesh_fn_hdf5}\n")
    pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn, mesh_idx=mesh_idx, skip_roi=True)
    pynibs.write_xdmf(mesh_fn_hdf5, overwrite_xdmf=True, verbose=True)

    print_mesh_info(mesh_fn_hdf5)

    # remove smoothed and refined meshes bc we created a new mesh.
    for fn in [mesh_fn_smoothed, mesh_fn_refined, mesh_fn_smoothed_hdf5, mesh_fn_refined_hdf5]:
        try:
            os.unlink(fn)
            logprint(f"Found {fn}. Removing.")
        except FileNotFoundError:
            pass

elif os.path.isfile(mesh_fn):
    logprint(f"{mesh_fn} exists. Skipping Meshing.")
    # if not os.path.exists(mesh_fn_org):
    #     logprint(f"Orginal mesh copy not found. Creating {mesh_fn_org}.")
    #
    #     shutil.copy(mesh_fn, mesh_fn_org)
    #     logprint(f" > Writing file: {mesh_fn_hdf5}\n")
    #     pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn_org, mesh_idx=mesh_idx, skip_roi=True)
    #     pynibs.write_xdmf(mesh_fn_org_hdf5, overwrite_xdmf=True, verbose=True)

    if not os.path.exists(mesh_fn_hdf5):
        logprint(f"{mesh_fn_hdf5} not found.")

        logprint(f" > Writing file: {mesh_fn_hdf5}\n")
        pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn, mesh_idx=mesh_idx, skip_roi=True)
        pynibs.write_xdmf(mesh_fn_hdf5, overwrite_xdmf=True, verbose=True)

if not os.path.exists(mesh_fn_org):
    # keep a copy of the original mesh file for housekeeping reasons
    shutil.copy(mesh_fn, mesh_fn_org)
    logprint(f" > Writing file: {mesh_fn_org_hdf5}\n")
    pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn_org, mesh_idx=mesh_idx, skip_roi=True)
    pynibs.write_xdmf(mesh_fn_org_hdf5, overwrite_xdmf=True, verbose=True)

# Create ROI
############################################################################################################
if mesh_idx in subject.roi.keys():
    for roi_name, roi in subject.roi[mesh_idx].items():
        time_start_roi = time.time()

        # only run ROI things if fn_mask does not exist yet
        if roi['fn_mask'] is not None and not os.path.exists(os.path.join(mesh_folder, roi['fn_mask'])):

            # Default to freesurfer ROI creation to keep backwards compat
            if roi['template'] in [None, 'fsaverage']:
                roi_dir = os.path.join(mesh_folder, "roi", str(roi_name))

                os.makedirs(roi_dir, exist_ok=True)

                logprint(f"Creating ROI '{roi_name}'")
                logprint(f"===============")

                # write bash script with the FreeSurfer commands
                f = open(os.path.join(roi_dir, "get_mask.sh"), "w")
                f.write(f"export SUBJECTS_DIR='{mesh_folder}'\n")
                f.write(f"cd {mesh_folder}\n")
                f.write(f"rm -f fsaverage\n")
                f.write(f"rm -f m2m_{subject.id}/surf\n")

                f.write(f"ln -s {fsaverage_dir} 'fsaverage'\n")
                f.write(f"ln -s 'surfaces' 'm2m_{subject.id}/surf'\n")

                f.write(f"mri_surf2surf "
                        f"--srcsubject 'fsaverage' "
                        f"--srcsurfval '{subject.roi[mesh_idx][roi_name]['fn_mask_avg']}' "
                        f"--trgsurfval {os.path.join(mesh_folder, roi['fn_mask'])} "
                        f"--hemi {roi['hemisphere']} "
                        f"--trgsubject m2m_{subject.id} "
                        f"--trgsurfreg sphere.reg.gii "
                        f"--srcsurfreg sphere.reg\n")
                f.close()

                # run FreeSurfer script
                command = f"sh {os.path.join(roi_dir, 'get_mask.sh')}"
                logprint(f"> Running '{command}'")
                os.popen(command).read()
else:
    print("No ROIs found in subject object.")

# Refine mesh
#####################################################
refined = False
if 'refinement_roi' in mesh_dict and mesh_dict['refinement_roi'] not in [None, '']:
    refined = True
    # create sphere that defines the refinement region
    final_tissues_nii = f"{mesh_folder}/m2m_{subject.id}/final_tissues.nii.gz"
    final_tissues_upsampled_nii = f"{mesh_folder}/m2m_{subject.id}/label_prep/tissue_labeling_upsampled.nii.gz"
    refinement_settings_fn = f"{mesh_folder}/m2m_{subject.id}/refinement_size.ini"

    if os.path.exists(mesh_fn_refined):
        logprint(f"Refined mesh {mesh_fn_refined} exists. Skipping refinement.")
        refine_now = False

    elif os.path.exists(refinement_upsampled_nii_fn):
        logprint(f"Using {refinement_upsampled_nii_fn} to refine.")
        refine_now = True

    else:
        logprint("Creating new refinement (upsampled) nii.")
        refine_now = True
        tissue_type_2_refine = [1, 2, 3]

        # get center of refinement sphere from roi
        refinement_roi = mesh_dict['refinement_roi']
        fn_roi = f"{mesh_folder}/{subject.roi[mesh_idx][refinement_roi]['fn_mask']}"
        refined_size = mesh_dict['refinemement_element_size']

        hem_roi_ref = subject.roi[mesh_idx][refinement_roi]['hemisphere']
        midlayer_fn = mesh_folder + '/' + mesh_dict[f'fn_{hem_roi_ref}_midlayer']
        roi_idx = np.where(nib.load(fn_roi).get_fdata()[:, 0, 0] != 0)[0]
        roi_points = nib.load(midlayer_fn).agg_data()[0]
        roi_center = np.mean(roi_points[roi_idx], axis=0)

        with open(refinement_settings_fn, 'w') as f:
            f.write(f"{refined_size}")

        # find maximum distance to center
        roi_radius = np.max(np.linalg.norm((roi_points[roi_idx] - roi_center), axis=1))

        # create spherical refinement .nii (T1 resolution)
        pynibs.create_refine_spherical_roi(center=roi_center,
                                           radius=roi_radius,
                                           target_size=refined_size,
                                           final_tissues_nii=final_tissues_nii,
                                           out_fn=refinement_nii_fn,
                                           outside_size=0,
                                           outside_factor=3,
                                           verbose=True)

        # create spherical refinement .nii (upsampled resolution)
        pynibs.create_refine_spherical_roi(center=roi_center,
                                           radius=roi_radius,
                                           target_size=refined_size,
                                           final_tissues_nii=final_tissues_upsampled_nii,
                                           out_fn=refinement_upsampled_nii_fn,
                                           outside_size=0,
                                           outside_factor=3,
                                           verbose=True)

    if refine_now:

        cmd = f'{meshmesh_cmdline} {final_tissues_upsampled_nii} ' \
              f'{mesh_fn_refined} --sizing_field={refinement_upsampled_nii_fn} {charm_ini_fn} ' + debug_flag

        logprint(f"Refinement: running {cmd}.")
        os.popen(cmd).read()

        # check mesh for degenerated elements
        zero_tris, zero_tets, neg_tets = pynibs.util.simnibs_io.check_mesh(mesh_fn_refined)
        if zero_tris.size or zero_tets.size or neg_tets.size:
            warnings.warn(f"Degenerated mesh {mesh_fn_refined}:\n "
                          f"{zero_tris.size} zero tris, "
                          f"{zero_tets.size} zero_tets, "
                          f"{neg_tets.size} neg_tets identified.")

        logprint(f" > Writing file: {mesh_fn_hdf5}\n")
        pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn_refined, mesh_idx=mesh_idx, skip_roi=True)
        pynibs.write_xdmf(mesh_fn_refined_hdf5, overwrite_xdmf=True, verbose=True)

        print_mesh_info(mesh_fn_refined_hdf5)

        for fn in [mesh_fn_smoothed, mesh_fn_smoothed_hdf5, mesh_fn, mesh_fn_hdf5]:
            try:
                os.unlink(fn)
                logprint(f"Found {fn}. Removing.")
            except FileNotFoundError:
                pass

        shutil.copy(mesh_fn_refined, mesh_fn)
        logprint(f" > Writing file: {mesh_fn_hdf5}\n")
        pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn, mesh_idx=mesh_idx, skip_roi=True)
        pynibs.write_xdmf(mesh_fn_hdf5, overwrite_xdmf=True, verbose=True)

# Mesh smoothing
#####################################################
if smooth_skin:
    if os.path.exists(mesh_fn_smoothed):
        f"f{mesh_fn_smoothed} found. Skipping smoothing."
    else:
        logprint(f"Smoothing skin surface with taubin filtering ({smooth_skin}).")
        # write smooth_setting.ini file to store smooth settings
        with open(smooth_settings_fn, 'w') as f:
            f.write(f"{smooth_skin}")

        smooth_mesh(mesh_fn,
                    mesh_fn_smoothed,
                    smooth=smooth_skin)

        # check mesh for degenerated elements
        zero_tris, zero_tets, neg_tets = pynibs.util.simnibs_io.check_mesh(mesh_fn_smoothed)
        if zero_tris.size or zero_tets.size or neg_tets.size:
            warnings.warn(f"Degenerated mesh {mesh_fn_smoothed}:\n "
                          f"{zero_tris.size} zero tris, "
                          f"{zero_tets.size} zero_tets, "
                          f"{neg_tets.size} neg_tets identified.")

        logprint(f" > Writing file: {mesh_fn_hdf5}\n")
        pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn_smoothed, mesh_idx=mesh_idx, skip_roi=True)

        pynibs.write_xdmf(mesh_fn_smoothed_hdf5, overwrite_xdmf=True, verbose=True)

        for fn in [mesh_fn, mesh_fn_hdf5]:
            try:
                os.unlink(fn)
                logprint(f"Found {fn}. Removing.")
            except FileNotFoundError:
                pass

        print_mesh_info(mesh_fn_smoothed_hdf5)

        shutil.copy(mesh_fn_smoothed, mesh_fn)
        logprint(f" > Writing file: {mesh_fn_hdf5}\n")
        pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn, mesh_idx=mesh_idx, skip_roi=True)
        pynibs.write_xdmf(mesh_fn_hdf5, overwrite_xdmf=True, verbose=True)

os.chdir(mesh_folder)

# fix mesh if neccessary
# =================================================================================================================
zero_tris, zero_tets, neg_tets = pynibs.util.simnibs_io.check_mesh(mesh_fn, verbose=True)
if zero_tris.size or zero_tets.size or neg_tets.size:
    logprint(f"Fixing degenerated elements.")
    for fn in [mesh_fn_hdf5, mesh_fn_unfixed]:
        try:
            os.unlink(fn)
        except FileNotFoundError:
            pass
    shutil.move(mesh_fn, mesh_fn_unfixed)
    mesh = pynibs.util.simnibs_io.fix_mesh(mesh_fn_unfixed)
    mesh.write(mesh_fn)

    logprint(
        f"Fixed {zero_tris.size} zero area triangles, {zero_tets.size} zero volume tets, {neg_tets.size}"
        f" negative volume tets")

    # check if new mesh is fine
    zero_tris, zero_tets, neg_tets = pynibs.util.simnibs_io.check_mesh(mesh_fn)
    if zero_tris.size or zero_tets.size or neg_tets.size:
        warnings.warn(f"Couldn't fix all elements for {mesh_fn}:\n "
                      f"{zero_tris.size} zero tris, "
                      f"{zero_tets.size} zero_tets, "
                      f"{neg_tets.size} neg_tets left over.")

# create *.hdf5 mesh file (incl. ROIs) from *.msh file
#############################################################################################################
logprint("Transforming mesh from .msh to .hdf5")
logprint(f"{'=' * 36}")

skip_msh2hdf5 = False

if os.path.exists(mesh_fn_hdf5):
    skip_msh2hdf5 = True
    logprint(f" > {mesh_fn_hdf5} already exists. Checking existence of ROIs ...")

    with h5py.File(mesh_fn_hdf5, "r") as f:
        if mesh_idx in subject.roi.keys():
            for roi_name in subject.roi[mesh_idx].keys():
                try:
                    _ = f[f"roi_surface/{roi_name}"]
                    logprint(f" > roi_surface/{roi_name} exists")

                except KeyError:
                    logprint(f" > roi_surface/{roi_name} does not exist")
                    skip_msh2hdf5 = False
                    break
else:
    skip_msh2hdf5 = False

if not skip_msh2hdf5:
    logprint(f" > Transforming .msh to .hdf5 and adding ROIs")
    pynibs.msh2hdf5(subject=subject, fn_msh=mesh_fn, mesh_idx=mesh_idx, skip_layer=np.logical_not(layer))
    logprint(f" > Writing file: {mesh_fn_hdf5}\n")

    # create .xdmf file for visualization in paraview
    pynibs.write_xdmf(mesh_fn_hdf5, overwrite_xdmf=True, verbose=True)
    logprint(f" > Created .xdmf file: {os.path.splitext(mesh_fn_hdf5)[0] + '.xdmf'}")

else:
    logprint(" > Skipping transformation from .msh to .hdf5 (already exists and all ROIs are included)")

roi = pynibs.load_roi_surface_obj_from_hdf5(fname=subject.mesh[mesh_idx]['fn_mesh_hdf5'])
if roi is not None:
    for roi_name in subject.roi[mesh_idx].keys():
        fn_geo_roi = os.path.join(mesh_folder, "roi", roi_name, "geo.hdf5")

        if not os.path.exists(fn_geo_roi):
            logprint(f" > Creating geo.hdf5 for ROI #{roi_name}: {fn_geo_roi}")

            if not os.path.exists(os.path.split(fn_geo_roi)[0]):
                os.makedirs(os.path.split(fn_geo_roi)[0])

            # midlayer .geo file
            pynibs.write_geo_hdf5_surf(out_fn=fn_geo_roi,
                                       points=roi[roi_name].node_coord_mid,
                                       con=roi[roi_name].node_number_list,
                                       replace=True,
                                       hdf5_path='/mesh')
            pynibs.write_xdmf(fn_geo_roi)

# determine anisotropic conductivity tensors
#############################################################################################################
d2c_folder = os.path.join(mesh_folder, f'm2m_{subject.id}', 'dMRI_prep')
create_conductivity_tensors = bvec is not None and \
                              bval is not None and \
                              dti_path is not None \
                              and not (os.path.exists(os.path.join(mesh_dict["mesh_folder"],
                                                                   mesh_dict['fn_tensor_vn']))
                                       and os.path.exists(os.path.join(d2c_folder,
                                                                       "first_ev_for_check.hdf5"))
                                       )
register_existing_tensor = dti_tensor_path is not None \
                           and not (os.path.exists(os.path.join(mesh_dict["mesh_folder"],
                                                                mesh_dict['fn_tensor_vn']))
                                    and os.path.exists(os.path.join(d2c_folder,
                                                                    "first_ev_for_check.hdf5"))
                                    )

if create_conductivity_tensors and not register_existing_tensor:
    time_start_dwi = time.time()
    tensor_fn = os.path.join(mesh_folder, f'm2m_{subject.id}', "dMRI_prep", "first_ev_for_check.msh")
    tensor_fn_hdf5 = tensor_fn.replace('.msh', 'hdf5')
    if not os.path.exists(os.path.join(mesh_folder, mesh_dict["fn_tensor_vn"])):
        try:
            os.remove(tensor_fn_hdf5)
        except FileNotFoundError:
            pass

        # fix .bvals to 0:
        assert os.path.exists(subject.mri[mri_idx]['fn_mri_DTI_bval']), \
            f"Can't find {subject.mri[mri_idx]['fn_mri_DTI_bval']}"

        with open(subject.mri[mri_idx]['fn_mri_DTI_bval'], 'r+') as f:
            f.seek(0)
            bvals = f.read()

            bvals = bvals.replace('\n', '')

            if bvals[-1] == " ":
                bvals = bvals[:-1]

            bvals = np.array(bvals.split(" ")).astype(int)

            if 0 not in bvals:
                min_val = np.min(bvals)
                assert min_val <= 10
                logprint(f"No b0 found in {subject.mri[mri_idx]['fn_mri_DTI_bval']}. Changing {min_val} to 0.")
                bvals[bvals == min_val] = 0
                bvals = " ".join(bvals.astype(str).tolist())
                shutil.copy(subject.mri[mri_idx]['fn_mri_DTI_bval'], subject.mri[mri_idx]['fn_mri_DTI_bval'] + '.org')
                f.seek(0)
                f.write(bvals)

        logprint("Charm version of dwi2cond")

        command = f"{dwi2cond_cmdline} " \
                  f"--all " \
                  f"--eddy " \
                  f"--readout={subject.mri[mri_idx]['dti_readout_time']}" \
                  f" --phasedir={subject.mri[mri_idx]['dti_phase_direction']} " \
                  f"{subject.id} {dti_path} {bval} {bvec} {dti_rev_path}"

        logprint("Creating anisotropic conductivity tensors from DWI data")
        logprint("=======================================================")
        logprint(f"Running {command}")

        os.putenv('SUBJECTS_DIR', os.getcwd())

        os.popen(command).read()
        logprint(f" > Created files in folder {os.path.join(mesh_folder, f'm2m_{subject.id}', 'dMRI_prep')}\n")

    elif register_existing_tensor:
        logprint(f"Using preprocess tensor file {dti_tensor_path} to create conductivity tensors.")
        time_start_dwi = time.time()
        tensor_fn = os.path.join(mesh_folder, f'm2m_{subject.id}', "dMRI_prep", "first_ev_for_check.msh")
        tensor_fn_hdf5 = tensor_fn.replace('.msh', 'hdf5')
        if not os.path.exists(os.path.join(mesh_folder, mesh_dict["fn_tensor_vn"])):
            try:
                os.remove(tensor_fn_hdf5)
            except FileNotFoundError:
                pass

        command = f"{dwi2cond_cmdline} " \
                  f"--all " \
                  f"{subject.id} {dti_tensor_path} "

        logprint("Creating anisotropic conductivity tensors from DWI data")
        logprint("=======================================================")
        logprint(f"Running {command}")

        # is this also necessary here? Not sure
        os.putenv('SUBJECTS_DIR', os.getcwd())

        os.popen(command).read()
        logprint(f" > Created files in folder {os.path.join(mesh_folder, f'm2m_{subject.id}', 'dMRI_prep')}\n")
    else:
        logprint(f" > Anisotropy files already exist ... skipping to create "
                 f"{mesh_dict['fn_tensor_vn']}")

    time_stop_dwi = time.time()
    time_dwi = time_stop_dwi - time_start_dwi

    if not os.path.exists(tensor_fn_hdf5):
        # write .hdf5 tensor file
        pynibs.msh2hdf5(subject=subject,
                        mesh_idx=mesh_idx,
                        fn_msh=tensor_fn,
                        skip_roi=True,
                        include_data=True)

logprint(f"Time: Creating mesh: {time_mesh:6.2f} secs")
if create_conductivity_tensors:
    logprint(f"Time:   Creating FA: {time_dwi:6.2f} secs")
logprint("============ DONE ============")
