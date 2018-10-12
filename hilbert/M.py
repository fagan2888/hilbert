import hilbert as h
try:
    from scipy import sparse, stats
    import numpy as np
    import torch
except ImportError:
    stats = None
    sparse = None
    np = None
    torch = None


class M:

    def __init__(
        self,
        bigram, 
        shift_by=None,
        neg_inf_val=None,
        clip_thresh=None,
        diag=None,
    ):

        self.bigram = bigram
        self.shift_by = shift_by
        self.neg_inf_val = neg_inf_val
        self.clip_thresh = clip_thresh
        self.diag = diag
        self.shape = self.bigram.Nxx.shape

    def calc_base(self, shard):
        raise NotImplementedError(
            'Use a concrete M class that implements calc_base().')

    def __getitem__(self, shard):
        # Calculate the basic elements of M.
        M_shard = self.calc_base(shard)
        # Apply effects to M.  Only apply diagonal value for diagonal shards.
        use_diag = self.diag if h.shards.on_diag(shard) else None
        affected_M = apply_effects(
            M_shard, self.shift_by, self.neg_inf_val,
            self.clip_thresh, use_diag
        )
        return affected_M

    def load_all(self):
        return self[h.shards.whole]


# TODO: test
class M_w2v(M):

    def __init__(self, *args, **kwargs):
        device = kwargs.pop('device', None) or h.CONSTANTS.MATRIX_DEVICE
        dtype = h.CONSTANTS.DEFAULT_DTYPE
        self.k = torch.tensor(kwargs.pop('k'), device=device, dtype=dtype)
        super().__init__(*args, **kwargs)

    def calc_base(self, shard):
        Nxx, Nx, Nxt, N = self.bigram.load_shard(shard)
        uNx, uNxt, uN = self.bigram.unigram.load_shard(shard)
        N_neg = negative_sample(Nxx, Nx, uNxt, uN, self.k)
        return torch.log(Nxx) - torch.log(N_neg)


def negative_sample(Nxx, Nx, uNxt, uN, k):
    return k * (Nx - Nxx) * (uNxt / uN)


class M_logNxx(M):
    def calc_base(self, shard):
        Nxx, Nx, Nxt, N = self.bigram.load_shard(shard)
        return torch.log(Nxx)


class M_pmi_star(M):
    def calc_base(self, shard):
        Nxx, Nx, Nxt, N = self.bigram.load_shard(shard)
        return h.corpus_stats.calc_PMI_star((Nxx, Nx, Nxt, N))


class M_pmi(M):
    def calc_base(self, shard):
        Nxx, Nx, Nxt, N = self.bigram.load_shard(shard)
        return h.corpus_stats.calc_PMI((Nxx, Nx, Nxt, N))



def get_M(M_name, **M_args):
    """
    Convenience function to be able to select and instantiate an M class by 
    name.
    """
    if M_name.lower() == 'pmi':
        return M_pmi(**M_args)
    elif M_name.lower() == 'w2v':
        return M_logNxx(**M_args)
    elif M_name.lower() == 'lognxx':
        return M_logNxx(**M_args)
    elif M_name.lower() == 'pmi_star':
        return calc_M_pmi_star
    else:
        raise ValueError(
            "Unexpected base for calculating M: %s.  "
            "Expected one of: 'pmi', 'w2v', 'logNxx', or 'pmi_star'."
        )


def apply_effects(
    M,
    shift_by=None,
    neg_inf_val=None,
    clip_thresh=None,
    diag=None
):
    # Optionally apply a variety of effects
    shift(M, shift_by)
    set_neg_inf(M, neg_inf_val) 
    clip_below(M, clip_thresh) 
    set_diag(M, diag)
    return M



### EFFECTS ###


def set_diag(M, val=None):
    if val is not None:
        h.utils.fill_diagonal(M, val)


def clip_below(M, thresh=None):
    if thresh is not None:
        M[M<thresh] = thresh


def set_neg_inf(M, val=None):
    if val is not None:
        M[M==-np.inf] = val


def shift(M, val=None):
    if val is not None:
        M += val


