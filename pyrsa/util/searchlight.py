import numpy as np
from scipy.spatial.distance import cdist
from tqdm import tqdm
from joblib import Parallel, delayed
import nibabel as nib

"""
This class was initially inspired by the following :
https://github.com/machow/pysearchlight
"""



def _get_searchlight_neighbors(mask, center, radius=3):
    """Return indices for searchlight where distance 
        between a voxel and their center < radius (in voxels)
    
    Args:
        center (index):  point around which to make searchlight sphere
    
    Returns:
        list: the list of volume indices that respect the 
                searchlight radius for the input center.  
    """
    center = np.array(center)
    mask_shape = mask.shape
    cx, cy, cz = np.array(center)
    x = np.arange(mask_shape[0])
    y = np.arange(mask_shape[1])
    z = np.arange(mask_shape[2])

    # First mask the obvious points
    # - may actually slow down your calculation depending.
    x = x[abs(x-cx) < radius]
    y = y[abs(y-cy) < radius]
    z = z[abs(z-cz) < radius]

    # Generate grid of points
    X, Y, Z = np.meshgrid(x, y, z)
    data = np.vstack((X.ravel(), Y.ravel(), Z.ravel())).T
    distance = cdist(data, center.reshape(1, -1), 'euclidean').ravel()

    return data[distance < radius].T.tolist()

def get_volume_searchlight(mask, radius=2, threshold=1):
    """Searches through the non-zero voxels of the mask, selects centers where 
        proportion of sphere voxels >= self.threshold.

    Args:
        mask ([numpy array]): binary brain mask
        radius (int, optional): [description]. Defaults to 2.
        threshold (int, optional): [description]. Defaults to 1.

    Returns:
        [numpy array]: array of centers of size n_centers x 3
        [list]: list of lists with neighbors - the length of the list will correspond to:
                n_centers x 3 x n_neighbors
    """

    centers = list(zip(*np.nonzero(mask)))
    good_centers = []
    good_neighbors = []

    for center in tqdm(centers, desc='Finding searchlights...'):
        neighbors = _get_searchlight_neighbors(mask, center, radius)
        if mask[neighbors].mean() >= threshold:
            good_centers.append(center)
            good_neighbors.append(neighbors)

    assert good_centers.shape[0] == len(good_neighbors), "number of centers and sets of neighbors do not match"
    print(f'Found {len(good_neighbors)} searchlights')

    return np.array(good_centers), good_neighbors



if __name__ == '__main__':
    data = np.load('/Users/daniel/Dropbox/amster/github/fmri_data/singe_trial_betas.npy')
    events = np.load('/Users/daniel/Dropbox/amster/github/fmri_data/singe_trial_events.npy')
    mask_img = nib.load('/Users/daniel/Dropbox/amster/github/fmri_data/sub-01_ses-01_task-WM_run-1_bold_space-MNI152NLin2009cAsym_brainmask.nii.gz')
    mask = mask_img.get_fdata()

    centers, neighbors = get_volume_searchlight(mask, radius=3, threshold=.7)