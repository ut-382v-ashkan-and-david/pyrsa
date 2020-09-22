import numpy as np
from scipy.spatial.distance import cdist
from tqdm import tqdm
from joblib import Parallel, delayed
from pyrsa.data.dataset import Dataset
from pyrsa.rdm.calc import calc_rdm
from pyrsa.rdm import RDMs

"""
Author: Daniel Lindh

This code was initially inspired by the following :
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

    return tuple(data[distance < radius].T.tolist())

def get_volume_searchlight(mask, radius=2, threshold=1.0):
    """Searches through the non-zero voxels of the mask, selects centers where 
        proportion of sphere voxels >= self.threshold.

    Args:
        mask ([numpy array]): binary brain mask
        radius (int, optional): the radius of each searchlight, defined in voxels. Defaults to 2.
        threshold (float, optional): Threshold of the proportion of voxels that need to be inside the brain mask
                                     in order for it to be considered a good searchlight center.
                                     Values go between 0.0 - 1.0 where 1.0 means that 100% of the voxels need to be inside
                                     the brain mask. Defaults to 1.0.

    Returns:
        [numpy array]: array of centers of size n_centers x 3
        [list]: list of lists with neighbors - the length of the list will correspond to:
                n_centers x 3 x n_neighbors
    """

    mask = np.array(mask)
    assert mask.ndim == 3, "Mask needs to be a 3-dimensional numpy array"

    centers = list(zip(*np.nonzero(mask)))
    good_centers = []
    good_neighbors = []

    for center in tqdm(centers, desc='Finding searchlights...'):
        neighbors = _get_searchlight_neighbors(mask, center, radius)
        if mask[neighbors].mean() >= threshold:
            good_centers.append(center)
            good_neighbors.append(neighbors)

    good_centers = np.array(good_centers)
    assert good_centers.shape[0] == len(good_neighbors), "number of centers and sets of neighbors do not match"
    print(f'Found {len(good_neighbors)} searchlights')

    # turn the 3-dim coordinates to array coordinates
    centers_raveled = np.ravel_multi_index(good_centers.T, mask.shape)
    neighbors_raveled = [np.ravel_multi_index(n, mask.shape) for n in good_neighbors]

    return centers_raveled, neighbors_raveled

def get_searchlight_RDMs(data_raveled, centers_raveled, neighbors_raveled, events,
                        method='correlation', verbose=True):
    """Iterates over all the searchlight centers and calculates the RDM 

    Args:
        data_raveled (2D numpy array): brain data, shape n_observations x n_channels (i.e. voxels/vertices)
        centers_raveled (1D numpy array): center indices for all searchlights as provided 
                                        by pyrsa.util.searchlight.get_volume_searchlight
        neighbors_raveled (list): list of lists with neighbor voxel indices for all searchlights 
                                        as provided by pyrsa.util.searchlight.get_volume_searchlight
        events (1D numpy array): 1D array of length n_observations
        method (str, optional): distance metric, see pyrsa.rdm.calc for options. Defaults to 'correlation'.
        verbose (bool, optional): Defaults to True.

    Returns:
        RDM [pyrsa.rdm.RDMs]: RDMs object with the RDM for each searchlight, the RDM.rdm_descriptors['voxel_index']
                              describes the center voxel index each RDM is associated with
    """

    # we can't run all centers at once, that will take too much memory
    # so lets to some chunking
    n_centers = centers_raveled.shape[0]
    chunked_center = np.split(np.arange(n_centers),
                              np.linspace(0, n_centers,
                              100, dtype=int)[1:-1])
    
    if verbose:
        print(f'\nDivided data into {len(chunked_center)} chunks!\n')
    
    # loop over chunks
    n_conds = len(np.unique(events))
    RDM = np.zeros((n_centers, n_conds * (n_conds-1) // 2))
    for chunk in tqdm(chunked_center, desc='Calculating RDMs...'):
        center_data = []
        for c in chunk:
            center = centers_raveled[c]
            nb = neighbors_raveled[c]

            ds = Dataset(data_raveled[:, nb],
                        descriptors={'center': c},
                        obs_descriptors={'events':events},
                        channel_descriptors={'voxels': nb})
            center_data.append(ds)

        RDM_corr = calc_rdm(center_data, method=method, descriptor='events')
        RDM[chunk, :] = RDM_corr.dissimilarities
    


    SL_rdms = RDMs(RDM,
                      rdm_descriptors={'voxel_index':centers_raveled},
                      dissimilarity_measure=method)

    return SL_rdms

def evaluate_models_searchlight(sl_RDM, models, eval_function, method='corr', n_jobs=1):
    """evaluates each searchlighth with the given model/models

    Args:
        sl_RDM ([pyrsa.rdm.RDMs]): RDMs object as computed by pyrsa.util.searchlight.get_searchlight_RDMs
        models ([pyrsa.model]: models to evaluate - can also be list of models
        eval_function (pyrsa.inference evaluation-function): [description]
        method (str, optional): see pyrsa.rdm.compare for specifics. Defaults to 'corr'.
        n_jobs (int, optional): how many jobs to run. Defaults to 1.

    Returns:
        [list]: list of with the model evaluate for each searchlight center
    """

    results = Parallel(n_jobs=n_jobs)(
                    delayed(eval_function)(
                        models, x) for x in tqdm(sl_RDM, desc='Evaluating models for each searchlight'))

    return results


if __name__ == '__main__':
    def upper_tri_indexing(RDM):
        """upper_tri_indexing returns the upper triangular index of an RDM
        
        Args:
            RDM 2Darray: squareform RDM
        
        Returns:
            1D array: upper triangular vector of the RDM
        """
        # returns the upper triangle
        m = RDM.shape[0]
        r, c = np.triu_indices(m, 1)
        return RDM[r, c]

    # Load data
    data = np.load('/Users/daniel/Dropbox/amster/github/fmri_data/singe_trial_betas.npy')
    events = np.load('/Users/daniel/Dropbox/amster/github/fmri_data/singe_trial_events.npy')
    mask_img = nib.load('/Users/daniel/Dropbox/amster/github/fmri_data/sub-01_ses-01_task-WM_run-1_bold_space-MNI152NLin2009cAsym_brainmask.nii.gz')
    mask = mask_img.get_fdata()

    # Get searchlights
    centers_raveled, neighbors_raveled = get_volume_searchlight(mask, radius=3, threshold=.7)

    # reshape data so we have n_observastions x n_voxels
    data_raveled = data.reshape([data.shape[0], -1])
    # Get RDMs
    RDM = get_searchlight_RDMs(data_raveled, centers_raveled, neighbors_raveled, events)

    # Evaluate our AlexNet layer 7 model
    from pyrsa.inference import eval_fixed
    from pyrsa.model import ModelFixed

    fc7_units = np.load('/Users/daniel/Dropbox/amster/github/fmri_data/unit_activations_fc7.npy')
    fc7 = RDMs(upper_tri_indexing(1-np.corrcoef(fc7_units)))
    fc7m = ModelFixed('fc7', fc7)

    fc8_units = np.load('/Users/daniel/Dropbox/amster/github/fmri_data/unit_activations_fc8.npy')
    fc8 = RDMs(upper_tri_indexing(1-np.corrcoef(fc8_units)))
    fc8m = ModelFixed('fc8', fc8)

    models = [fc7m, fc8m]

    eval_results = evaluate_models_searchlight(RDM, fc7m, eval_fixed, method='corr', n_jobs=2)
    # get the evaulation score for each voxel
    eval_score = [float(eval_results[c].evaluations) for c in range(len(centers_raveled))]

    x, y, z = mask.shape
    RDM_brain = np.zeros([x*y*z])
    RDM_brain[list(RDM.rdm_descriptors['voxel_index'])] = eval_score
    RDM_brain = RDM_brain.reshape([x, y, z])


    # we can also save the upper triangle RDM for each voxel as a nifti
    x, y, z = mask.shape
    n_conds = len(np.unique(events))
    n_comparisons = n_conds * (n_conds-1) // 2
    RDM_brain = np.zeros([x*y*z, n_comparisons])
    RDM_brain[list(RDM.rdm_descriptors['voxel_index']), :] = RDM.dissimilarities
    RDM_brain = RDM_brain.reshape([x, y, z, n_comparisons]
    

    
    






