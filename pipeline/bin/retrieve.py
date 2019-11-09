import time
import os
import pandas as pd
import tempfile
from pathlib import Path
import subprocess
import db


def submit_hpss_job(tarfiles, images, job_script_destination,
                    frame_destination, log_destination,
                    tape_number):

    nersc_account = os.getenv('NERSC_ACCOUNT')

    if job_script_destination is None:
        # then just use temporary files

        jobscript = tempfile.NamedTemporaryFile()
        subscript = tempfile.NamedTemporaryFile()

    else:

        jobscript = open(Path(job_script_destination) / f'hpss.{tape_number}.sh', 'w')
        subscript = open(Path(job_script_destination) / f'hpss.{tape_number}.sub.sh', 'w')

    substr =  f'''#!/usr/bin/env bash
#module load esslurm
export PATH=/global/common/cori/software/hypnotoad:/opt/esslurm/bin:$PATH
export LD_LIBRARY_PATH=/opt/esslurm/lib64:$LD_LIBRARY_PATH
sbatch {Path(jobscript.name).resolve()}
'''

    if job_script_destination is None:
        substr = substr.encode('ASCII')

    subscript.write(substr)

    hpt = f'hpss.{tape_number}'

    jobstr = f'''#!/usr/bin/env bash
#SBATCH -J {tape_number}
#SBATCH -L SCRATCH,project
#SBATCH -q xfer
#SBATCH -N 1
#SBATCH -A {nersc_account}
#SBATCH -t 48:00:00
#SBATCH -C haswell
#SBATCH -o {(Path(log_destination) / hpt).resolve()}.out

cd {Path(frame_destination).resolve()}

'''

    for tarfile, imlist in zip(tarfiles, images):
        wildimages = '\n'.join([f'*{p}' for p in imlist])

        directive = f'''
/usr/common/mss/bin/hsi get {tarfile}
echo "{wildimages}" | tar --strip-components=12 -i --wildcards --wildcards-match-slash --files-from=- -xvf {os.path.basename(tarfile)}
rm {os.path.basename(tarfile)}

'''
        jobstr += directive

    if job_script_destination is None:
        jobstr = jobstr.encode('ASCII')

    jobscript.write(jobstr)

    jobscript.seek(0)
    subscript.seek(0)

    command = f'/bin/bash {Path(subscript.name).resolve()}'
    p = subprocess.Popen(command.split(), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    #stdout, stderr = p.communicate()

    while True:
        if p.poll() is not None:
            break
        else:
            time.sleep(0.01)

    stdout, stderr = p.stdout, p.stderr
    retcode = p.returncode

    out = stdout.readlines()
    err = stderr.readlines()

    print(out, flush=True)
    print(err, flush=True)

    if retcode != 0:
        raise ValueError(f'Nonzero return code ({retcode}) on command, "{command}"')

    jobscript.close()
    subscript.close()

    jobid = int(out[0].strip().split()[-1])

    return jobid


def retrieve_images(query, exclude_masks=False, job_script_destination=None,
                    frame_destination='.', log_destination='.'):

    # this is the query to get the image paths
    metatable = pd.read_sql(query.statement, db.DBSession().get_bind())

    df = metatable[['path', 'hpss_sci_path', 'hpss_mask_path']]
    dfsci = df[['path', 'hpss_sci_path']]
    dfsci = dfsci.rename({'hpss_sci_path': 'tarpath'}, axis='columns')

    if not exclude_masks:
        dfmask = df[['path', 'hpss_mask_path']].copy()
        dfmask.loc[:, 'path'] = [im.replace('sciimg', 'mskimg') for im in dfmask['path']]
        dfmask = dfmask.rename({'hpss_mask_path': 'tarpath'}, axis='columns')
        dfmask.dropna(inplace=True)
        df = pd.concat((dfsci, dfmask))
    else:
        df = dfsci

    tars = df['tarpath'].unique()

    # if nothing is found raise valueerror
    if len(tars) == 0:
        raise ValueError('No images match the given query')

    instr = '\n'.join(tars.tolist())

    with tempfile.NamedTemporaryFile() as f:
        f.write(f"{instr}\n".encode('ASCII'))

        # rewind the file
        f.seek(0)

        # sort tarball retrieval by location on tape
        sortexec = Path(__file__).parent / 'hpsssort.sh'
        syscall = f'bash {sortexec} {f.name}'
        p = subprocess.Popen(syscall.split(), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)

        while True:
            if p.poll() is not None:
                break
            else:
                time.sleep(0.01)

        retcode = p.returncode
        stderr, stdout = p.stderr, p.stdout

        if retcode != 0:
            raise subprocess.CalledProcessError(stderr.read())

        # read it into pandas
        ordered = pd.read_csv(stdout, delim_whitespace=True, names=['tape',
                                                                    'position',
                                                                    '_',
                                                                    'hpsspath'])

    # submit the jobs based on which tape the tar files reside on
    # and in what order they are on the tape

    dependency_dict = {}
    for tape, group in ordered.groupby('tape'):

        # get the tarfiles
        tarnames = group['hpsspath'].tolist()
        images = [df[df['tarpath'] == tarname]['path'].tolist() for tarname in tarnames]

        jobid = submit_hpss_job(tarnames, images, job_script_destination, frame_destination, log_destination, tape)
        for image in df[[name in tarnames for name in df['tarpath']]]['path']:
            dependency_dict[image] = jobid

    return dependency_dict, metatable
