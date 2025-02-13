#!/usr/bin/env python

"""Utilities used for connectivity analysis."""

import sys
import os.path as op
import numpy as np
import mne


def find_distances_matrix(con, epochs, picks_epochs):

    """Calculate distances between sensors.

    Function calculates distances between sensors (distance in mm mostly).

    The distances are in millimetres.

    Parameters:
    -----------
    con : ndarray
        Connectivity matrix.
    epochs : Epochs object.
        Instance of mne.Epochs
    picks_epochs : list
        Picks of epochs to be considered for analysis.

    Returns:
    --------
    con_dist : ndarray
         Connectivity distance matrix. Matrix of distances between various sensors.

    """
    ch_names = epochs.ch_names
    idx = [ch_names.index(name) for name in ch_names]
    sens_loc = [epochs.info['chs'][picks_epochs[i]]['loc'][:3] for i in idx]
    sens_loc = np.array(sens_loc)
    con_dist = np.zeros(con.shape)
    from scipy import linalg
    for i in range(0, 31):
        for j in range(0, 31):
            con_dist[i][j] = linalg.norm(sens_loc[i] - sens_loc[j])
    return con_dist


def weighted_con_matrix(con, epochs, picks_epochs, sigma=20):
    """Compute the weighted connectivity matrix.

    A normalized gaussian weighted matrix is computed and added to the
    true connectivity matrix.

    Parameters
    ----------
    con : ndarray (n_channels x n_channels)
        Connectivity matrix.
    epochs : Epochs object.
        Instance of mne.Epochs
    picks_epochs : list
        Picks of epochs to be considered for analysis.
    sigma : int
        Standard deviation of the gaussian function used for weighting.

    Returns
    -------
    weighted_con_matrix : ndarray (n_channels x n_channels)
        Gaussian distance weighted connectivity matrix.

    """
    con_dist = find_distances_matrix(con, epochs, picks_epochs)

    con_dist_range = np.unique(con_dist.ravel())
    # gaussian function for weighting, sigma - standard deviation
    from scipy.signal import gaussian
    gaussian_function = gaussian(con_dist_range.size * 2, sigma)[:con_dist_range.size]
    # Calculate the weights
    normalized_weights = (con_dist_range * gaussian_function) / np.sum(con_dist_range * gaussian_function)
    # make a dictionary with distance and respective weights values
    # d{sensor_distances:gaussian_normalized_weights}
    d = {}
    for i in range(0, con_dist_range.size):
        d[con_dist_range[i]] = normalized_weights[i]
    # compute the distance weights matrix
    dist_weights_matrix = np.zeros(con_dist.shape)
    for j in range(0, con_dist.shape[0]):
        for k in range(0, con_dist.shape[0]):
            dist_weights_matrix[j][k] = d[con_dist[j][k]]
    # add the weights matrix to connectivity matrix to get the weighted connectivity matrix
    weighted_con_matrix = con + dist_weights_matrix
    return weighted_con_matrix


def make_communities(con, top_n=3):
    """Make communities.

    Given an adjacency matrix, return list of nodes belonging to the top_n
    communities based on Networkx Community algorithm.

    Returns:
    --------
    top_nodes_list: list (of length top_n)
        Indices/nodes of the network that belongs to the top_n communities
    n_communities: int
        Total number of communities found by the algorithm.

    """
    import networkx as nx
    import community
    G = nx.Graph(con)

    # apply the community detection algorithm
    part = community.best_partition(G)

    from collections import Counter
    top_communities = Counter(list(part.values())).most_common()[:top_n]
    n_communities = len(Counter(list(part.values())))
    # gets tuple (most_common, number_most_common)
    top_nodes_list = []
    for common, _ in top_communities:
        top_nodes_list.append([node_ind for node_ind in part if part[node_ind] == common])

    # nx.draw_networkx(G, pos=nx.spring_layout(G), cmap=plt.get_cmap("jet"),
    #                  node_color=values, node_size=35, with_labels=False)

    return top_nodes_list, n_communities


def get_label_distances(subject, subjects_dir, parc='aparc'):
    """Get Euclidean distance between label center of masses.

    Get the Euclidean distance between label center of mass and return the
    distance matrix. The distance are computed between vertices in the MNI
    coordinates in the subject source space.

    Parameters:
    -----------
    subject: str
        Name of the subject.
    subjects_dir: str
        The subjects directory.
    parc: str
        Name of the parcellation. Default 'aparc'.

    Return:
    -------
    rounded_com: ndarray | (N, N)
        The distance between center of masses of different labels
    coords_all: ndarray | (N, )
        The MNI coordinates of the vertices in the source space.
    coms_lh, coms_rh: list | (N, )
        The centre of masses of labels in left and right hemispheres.

    """
    import itertools
    from scipy import linalg

    # get the labels
    aparc = mne.read_labels_from_annot(subject, subjects_dir=subjects_dir,
                                       parc=parc)
    # get rid of the unknown label
    aparc = [apa for apa in aparc if apa.name.find('unknown') == -1]

    N = len(aparc)  # get the number of labels

    # get the center of mass of each of the labels and
    coords_all, coms_lh, coms_rh = [], [], []
    for mylab in aparc:
        # now, split between hemispheres
        if mylab.name.endswith('-lh'):
            com_lh = mylab.center_of_mass(subject, subjects_dir=subjects_dir)
            coords_ = mne.vertex_to_mni(com_lh, hemis=0, subject=subject,
                                        subjects_dir=subjects_dir)
            coms_lh.append(com_lh)
        else:
            com_rh = mylab.center_of_mass(subject, subjects_dir=subjects_dir)
            coords_ = mne.vertex_to_mni(com_rh, hemis=1, subject=subject,
                                        subjects_dir=subjects_dir)
            coms_rh.append(com_rh)

        coords_all.append(coords_)

    # compute the distances
    com_distances = np.zeros((N, N))
    for (i, j) in itertools.combinations(list(range(N)), 2):
        com_distances[i, j] = linalg.norm(coords_all[i] - coords_all[j])

    # only one half matrix is created above, make it full
    com_distances += com_distances.T

    rounded_com = np.round(com_distances, 0)

    # return the distance matrix rounded to nearest integer
    return rounded_com, np.array(coords_all), coms_lh, coms_rh


def make_annot_from_csv(subject, subjects_dir, csv_fname, lab_size=10,
                        parc_fname='standard_garces_2016',
                        n_jobs=4, make_annot=False, return_label_coords=False):
    """Make annotations from given csv file.
    
    For a given subject, given a csv file with set of MNI coordinates,
    make an annotation of labels grown from these ROIs.
    Mainly used to generate standard resting state network annotation from
    MNI coordinates provided in literature.

    Parameters:
    -----------
    subject: str
        The name of the subject.
    subjects_dir: str
        The SUBJECTS_DIR where the surfaces are available.
    csv_fname: str
        Comma separated file with seed MNI coordinates.
        # example
        Network,Node,x,y,z,BA,hemi
        Visual,Left visual cortex,-41,-77,3,19,lh
    lab_size: int
        The size of the label (radius in mm) to be grown around ROI coordinates
    parc_fname: str
        Name used to save the parcellation as if make_annot is True.
    n_jobs: int
        Number of parallel jobs to run.
    make_annot: bool
        If True, an annotation file is created and written to disk.
    return_label_coords: bool
        If True, the function returns labels and MNI seed coordinates used.

    """
    from mne import grow_labels
    import pandas as pd
    import matplotlib.cm as cmx
    import matplotlib.colors as colors
    from surfer import (Surface, utils)

    surf = 'white'
    hemi = 'both'

    rsns = pd.read_csv(csv_fname, comment='#')

    all_coords, all_labels = [], []
    all_foci = []
    for netw in rsns.Network.unique():
        print(netw, end=' ')
        nodes = rsns[rsns.Network == netw]['Node'].values
        for node in nodes:
            mni_coords = rsns[(rsns.Network == netw) &
                              (rsns.Node == node)].loc[:, ('x', 'y', 'z')].values[0]
            all_coords.append(mni_coords)

            hemi = rsns[(rsns.Network == netw) & (rsns.Node == node)].hemi.values[0]
            print(node, ':', mni_coords, hemi, end=' ')

            # but we are interested in getting the vertices and
            # growing our own labels
            foci_surf = Surface(subject, hemi=hemi, surf=surf,
                                subjects_dir=subjects_dir)
            foci_surf.load_geometry()
            foci_vtxs = utils.find_closest_vertices(foci_surf.coords,
                                                    mni_coords)
            print('Closest vertex on surface chosen:', foci_vtxs)
            all_foci.append(foci_vtxs)

            if hemi == 'lh':
                hemis = 0
            else:
                hemis = 1  # rh

            lab_name = netw + '_' + node
            mylabel = grow_labels(subject, foci_vtxs, extents=lab_size,
                                  hemis=hemis, subjects_dir=subjects_dir,
                                  n_jobs=n_jobs, overlap=True,
                                  names=lab_name, surface=surf)[0]
            all_labels.append(mylabel)

    # assign colours to the labels
    # labels within the same network get the same color
    n_nodes = len(rsns.Node.unique())
    # n_networks = len(rsns.Network.unique())  # total number of networks
    color_norm = colors.Normalize(vmin=0, vmax=n_nodes-1)
    scalar_map = cmx.ScalarMappable(norm=color_norm, cmap='hsv')
    for n, lab in enumerate(all_labels):
        lab.color = scalar_map.to_rgba(n)

    if make_annot:
        mne.label.write_labels_to_annot(all_labels, subject=subject,
                                        parc=parc_fname,
                                        subjects_dir=subjects_dir)

    if return_label_coords:
        # returns the list of labels grown and MNI coords used as seeds
        return all_labels, all_coords, all_foci


def expand_con_matrix(con, label_names, full_label_names):
    """Expand the dimensions of the connectivity matrix.

    The dimensions are expaded from
    (len(label_names), len(label_names) to
    (len(full_label_names), len(full_label_names)).

    Parameters:
    -----------
    con : np.array of shape (len(label_names), len(label_names)
        The connectivity matrix to be expanded.
    label_names : list
        List containing the label names corresponding to the
        indices of the connectivity matrix.
    full_label_names : list
        Full list containing all label names to be included in the
        expanded connectivity matrix.

    Returns:
    --------
    con_exp : np.array of shape (len(full_label_names), len(full_label_names))
        The full connectivity matrix after expansion.

    """
    assert len(con.shape) == 2, 'The con matrix is not 2D.'
    assert con.shape[0] == con.shape[1], 'The con matrix is not square.'
    assert con.shape[0] == len(label_names), 'Number of labels and con matrix shape do not match.'

    full_label_names_arr = np.asarray(full_label_names)

    lbl_indices = []
    for ln in label_names:
        lbl_indices.append(np.where(full_label_names_arr == ln)[0][0])
    lbl_indices = np.asarray(lbl_indices)

    if len(label_names) != len(lbl_indices):
        raise RuntimeError('Not all labels could be matched.')

    con_exp = np.zeros((len(full_label_names), len(full_label_names)))

    for ii in range(lbl_indices.shape[0]):

        for jj in range(lbl_indices.shape[0]):
            idxi = lbl_indices[ii]
            idxj = lbl_indices[jj]

            con_exp[idxi, idxj] = con[ii, jj]

    if not np.allclose(con_exp[lbl_indices][:, lbl_indices], con):
        raise RuntimeError('Expansion failed.')

    return con_exp


def group_con_matrix_by_lobe(con, label_names, grouping_yaml_fname):
    """Group and sum up entries in the connectivity matrix by lobes.

    Parameters:
    -----------
    con : np.array of shape (len(label_names), len(label_names)
        The connectivity matrix to be summed up.
    label_names : list
        List containing the label names corresponding to the
        indices of the connectivity matrix.
    grouping_yaml_fname : str
        Path to the file grouping labels by lobes.

    Returns:
    --------
    con_grp_exp : np.array of shape (n_lobes, n_lobes)
        The grouped connectivity matrix.

    """
    assert len(con.shape) == 2, 'The con matrix is not 2D.'
    assert con.shape[0] == con.shape[1], 'The con matrix is not square.'
    assert con.shape[0] == len(label_names), 'Number of labels and con matrix shape do not match.'

    if op.isfile(grouping_yaml_fname):
        import yaml
        with open(grouping_yaml_fname, 'r') as f:
            groupings = yaml.safe_load(f)
    else:
        print('%s - File not found.' % grouping_yaml_fname)
        sys.exit()

    ###########################################################################
    # Get the indices of the labels belonging to the lobes
    ###########################################################################

    full_grouping_labels = []
    grouping_labels = []
    grouping_indices = []
    for grouping in groupings:

        for key in grouping:
            grp_indices_lh = []
            grp_indices_rh = []

            for label_name in label_names:

                if not (label_name.endswith('-lh') or label_name.endswith('-rh')):
                    raise RuntimeError('Label is neither left nor right hemisphere.')

                if label_name[:-3] in grouping[key]:
                    if label_name.endswith('-lh'):
                        grp_indices_lh.append(label_names.index(label_name))
                    else:
                        grp_indices_rh.append(label_names.index(label_name))

            if len(grp_indices_lh) > 0:
                grouping_labels.append(key + '-lh')
                grouping_indices.append(np.asarray(grp_indices_lh))
            if len(grp_indices_rh) > 0:
                grouping_labels.append(key + '-rh')
                grouping_indices.append(np.asarray(grp_indices_rh))

            full_grouping_labels.extend([key + '-lh', key + '-rh'])

    ###########################################################################
    # Create the grouping by lobe in two steps
    ###########################################################################

    # ensure that diagonal values are 0 before summing
    con = con.copy()
    np.fill_diagonal(con, 0)

    # first sum up across rows
    # then sum up across columns

    con_row = np.empty(shape=(len(grouping_labels), con.shape[1]))
    for idx in range(len(grouping_indices)):
        grp_indices = grouping_indices[idx]
        con_row[idx] = con[grp_indices].sum(axis=0)

    con_grp = np.empty(shape=(len(grouping_labels), len(grouping_labels)))
    for idx in range(len(grouping_indices)):
        grp_indices = grouping_indices[idx]
        con_grp[:, idx] = con_row[:, grp_indices].sum(axis=1)

    con_grp_exp = expand_con_matrix(con_grp, grouping_labels, full_grouping_labels)

    return con_grp_exp, full_grouping_labels


def generate_random_connectivity_matrix(size=(68, 68), symmetric=False,
                                        random_state=37):
    """Make a random connectivity matrix.

    A square connectivity style matrix with pseudo Gaussian connectivity
    values between 0 and 1 is generated.

    Parameters:
    -----------
    size: tuple
      Size of the matrix. Has to be 2d ndaray.
    symmetric: bool
            If True, returns a symmetric matrix.
    random_state: None | int | array
            Seed to initialise random state generator.

    Returns:
    --------
    con: ndarray

    """
    rng = np.random.RandomState(random_state)
    con = rng.normal(loc=0.5, scale=0.2, size=size)
    con[(con <= 0.) | (con > 1.)] = 0.  # make 0 < con < 1
    con[np.diag_indices_from(con)] = 0.  # zero diagonal
    con[np.triu_indices_from(con)] = 0.  # zero upper half
    if symmetric:
        return con + con.T
    else:
        return con


def load_grouping_dict(grouping):
    """Load cortex or cluster based grouping information."""
    import yaml
    if isinstance(grouping, str):
        # read the yaml file with grouping
        if op.isfile(grouping):
            with open(grouping, 'r') as f:
                my_groups = yaml.safe_load(f)
        else:
            print('%s - File not found.' % grouping)
            sys.exit()
    elif isinstance(grouping, list):
        # should be a list of dictionaries
        my_groups = grouping
    else:
        raise RuntimeError('yaml_fname should be one of str or list')
    return my_groups
