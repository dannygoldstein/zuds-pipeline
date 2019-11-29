import os
import db
import numpy as np
import shutil
import pandas as pd

from utils import initialize_directory
from seeing import estimate_seeing


import tempfile
from pathlib import Path
import paramiko

# split an iterable over some processes recursively
_split = lambda iterable, n: [iterable[:len(iterable)//n]] + \
             _split(iterable[len(iterable)//n:], n - 1) if n != 0 else []


def chunk(iterable, chunksize):
    isize = len(iterable)
    nchunks = isize // chunksize if isize % chunksize == 0 else isize // chunksize + 1
    for i in range(nchunks):
        yield i, iterable[i * chunksize : (i + 1) * chunksize]


def make_coadd_bins(science_rows, window_size=3, rolling=False):

    mindate = pd.to_datetime(science_rows['obsdate'].min())
    maxdate = pd.to_datetime(science_rows['obsdate'].max())


    if rolling:
        dates = pd.date_range(mindate, maxdate, freq='1D')
        bins = []
        for i, date in enumerate(dates):
            if i + window_size >= len(dates):
                break
            bins.append((date, dates[i + window_size]))

    else:
        binedges = pd.date_range(mindate, maxdate, freq=f'{window_size}D')

        bins = []
        for i, lbin in enumerate(binedges[:-1]):
            bins.append((lbin, binedges[i + 1]))

    return bins


def prepare_hotpants(sci, ref, outname, submask, directory,
                     copy_inputs=False, tmpdir='/tmp'):

    initialize_directory(directory)

    # if requested, copy the input images to a temporary working directory
    if copy_inputs:
        impaths = []
        for image in [sci, ref]:
            shutil.copy(image.local_path, directory)
            impaths.append(str(directory / image.basename))
    else:
        impaths = [im.local_path for im in [sci, ref]]
    scipath, refpath = impaths

    if 'SEEING' not in sci.header:
        estimate_seeing(sci)
        sci.save()

    seepix = sci.header['SEEING']  # header seeing is FWHM in pixels
    r = 2.5 * seepix
    rss = 6. * seepix

    nsx = sci.header['NAXIS1'] / 100.
    nsy = sci.header['NAXIS2'] / 100.

    # get the background for the input images
    scirms = sci.rms_image
    refrms = ref.parent_image.rms_image.aligned_to(scirms, tmpdir=tmpdir)

    # save temporary copies of rms images if necessary
    if not scirms.ismapped or copy_inputs:
        scirms_tmpnam = str((directory / scirms.basename).absolute())
        scirms.map_to_local_file(scirms_tmpnam)
        scirms.save()

    if not refrms.ismapped or copy_inputs:
        refrms_tmpnam = str((directory / refrms.basename).absolute())
        refrms.map_to_local_file(refrms_tmpnam)
        refrms.save()

    # we only need a quick estimate of the bkg.
    # so we mask out any pixels where the MASK value is non zero.

    NSAMP = 10000

    scibkgpix = sci.data[sci.mask_image.data == 0]
    scibkgpix = np.random.choice(scibkgpix, size=NSAMP)

    refbkgpix = ref.data[ref.mask_image.data == 0]
    refbkgpix = np.random.choice(refbkgpix, size=NSAMP)

    scibkg = np.median(scibkgpix)
    refbkg = np.median(refbkgpix)

    scibkgstd = np.std(scibkgpix)
    refbkgstd = np.std(refbkgpix)

    il = scibkg - 10 * scibkgstd
    tl = refbkg - 10 * refbkgstd

    satlev = 5e4  # not perfect, but close enough.

    syscall = f'hotpants -inim {scipath} -hki -n i -c t ' \
              f'-tmplim {ref.local_path} -outim {outname} ' \
              f'-tu {satlev} -iu {satlev}  -tl {tl} -il {il} -r {r} ' \
              f'-rss {rss} -tni {refrms.local_path} ' \
              f'-ini {scirms.local_path} ' \
              f'-imi {submask.local_path} ' \
              f'-nsx {nsx} -nsy {nsy}'

    return syscall


