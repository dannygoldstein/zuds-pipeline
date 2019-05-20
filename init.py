import os

#########################################################################
# Modify these variables to point to the right values for you.
# Then execute this file to propagate these values forward to the pipeline
#########################################################################

nersc_account = '***REMOVED***'
nersc_username = 'dgold'
nersc_password = '***REMOVED***'
marshal_username = 'dannygoldstein'
marshal_password = '***REMOVED***'
lensgrinder_home = '/global/cscratch1/sd/dgold/lensgrinder'
run_topdirectory = '/global/cscratch1/sd/dgold/knproc'
hpss_dbhost = '***REMOVED***'
hpss_dbport = 6666
hpss_dbusername = '***REMOVED***'
hpss_dbname = 'decam'
hpss_dbpassword = '***REMOVED***'
shifter_image = 'registry.services.nersc.gov/dgold/improc:latest'
slurm_email = 'ztfcoadd@gmail.com'


#########################################################################
# Don't change the values of anything after this line
#########################################################################

volume_mounts = {
    os.path.join(lensgrinder_home, 'pipeline'): '/pipeline',
    os.path.join(lensgrinder_home, 'pipeline', 'scripts'): '/scripts',
    os.path.join(run_topdirectory, 'noao'): '/output',
    os.path.join(run_topdirectory, 'calibdata'): '/calibdata',
    f'/global/homes/{nersc_username[0].lower()}/{nersc_username}': '/home/desi',
    lensgrinder_home: '/lensgrinder',
    os.path.join(lensgrinder_home, 'ingest', 'job_scripts'): '/job_scripts',
    os.path.join(lensgrinder_home, 'process'): '/process',
    os.path.join(lensgrinder_home, 'pipeline', 'astromatic'): '/astromatic'
}

logdir = os.path.join(lensgrinder_home, 'ingest', 'logs')

environment_variables = {
    'HPSS_DBHOST': hpss_dbhost,
    'HPSS_DBPORT': hpss_dbport,
    'HPSS_DBUSERNAME': hpss_dbusername,
    'HPSS_DBPASSWORD': hpss_dbpassword,
    'HPSS_DBNAME': hpss_dbname,
    'MARSHAL_USERNAME': marshal_username,
    'MARSHAL_PASSWORD': marshal_password,
    'NERSC_USERNAME': nersc_username,
    'NERSC_PASSWORD': nersc_password
}

estring = ' '.join([f" -e {k}='{environment_variables[k]}'" for k in environment_variables])
vstring = ';'.join([f'{k}:{volume_mounts[k]}' for k in volume_mounts])

with open('shifter.sh', 'w') as f:
    f.write(f'''#!/bin/bash
shifter --volume="{vstring}" \
        --image={shifter_image} \
        {estring} /bin/bash
''')

with open('process_focalplane.sh', 'w') as f:
    f.write(f'''#!/usr/bin/env bash

#SBATCH -N 1
#SBATCH -J $1
#SBATCH -t 00:30:00
#SBATCH -L SCRATCH
#SBATCH -A {nersc_account}
#SBATCH --mail-type=ALL
#SBATCH --partition=realtime
#SBATCH --mail-user={slurm_email}
#SBATCH --image={shifter_image}
#SBATCH -C haswell
#SBATCH --exclusive
#SBATCH --volume="{vstring}"
#SBATCH -o {os.path.join(logdir, 'slurm-%A.out')}

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

start=`date +%s`

# split the exposure into individual fitsfiles
shifter python /pipeline/bin/split_exposure.py /output/$1

# run preprocess and get the good wcs calibrations
srun -n 64 shifter {estring} python /pipeline/bin/preprocess.py /output/$2/$1.list

# determine all of the images that overlap with all of the chip images
if ! srun -n 64 shifter {estring} python /pipeline/bin/make_base_template.py /output/$2/$1.list; then
    echo "image $1 has no template coverage, so cannot be processed. exiting..."
    exit 1 
fi

# now actually run the pipeline
srun -n 64 shifter {estring} python /process/process.py /output/$2/$1.list 

end=`date +%s`

runtime=$((end-start))

echo runtime was $runtime

''')

with open('interactive.sh', 'w') as f:
    f.write(f'''salloc -N 1 -t 00:30:00 -L SCRATCH -A {nersc_account} \
--partition=realtime --image={shifter_image} -C haswell --exclusive \
--volume="{vstring}"''')
