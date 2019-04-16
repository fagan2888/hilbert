import abc
import hilbert as h
import torch
import torch.distributions as dist
from math import ceil
from hilbert.generic_datastructs import Describable, \
    build_sparse_lil_nxx, build_sparse_tup_nxx


class BatchPreloader(Describable):
    """
    Abstract class for batch preloading.
    """

    @abc.abstractmethod
    def __init__(
            self, cooccurrence_path, *args,
            t_clean_undersample=None,
            alpha_unigram_smoothing=None, **kwargs
        ):

        self.cooccurrence_path = cooccurrence_path
        self.t_clean_undersample = t_clean_undersample
        self.alpha_unigram_smoothing = alpha_unigram_smoothing


    @abc.abstractmethod
    def preload_iter(self, *args, **kwargs):
        return


    def prepare(self, preloaded):
        return preloaded


    @abc.abstractmethod
    def describe(self):
        s = '\tcooccurrence_path = {}\n'.format(self.cooccurrence_path)
        s += '\tt_clean_undersample = {}\n'.format(self.t_clean_undersample)
        s += '\talpha_unigram_smoothing = {}\n'.format(
            self.alpha_unigram_smoothing)
        return s




class DenseShardPreloader(BatchPreloader):
    """
    Class for dense matrix factorization data loading.
    """

    def __init__(
        self, cooccurrence_path, sector_factor, shard_factor,
        t_clean_undersample=None,
        alpha_unigram_smoothing=None, verbose=True
    ):
        """
        Base class for more specific loaders `CooccurrenceLoader` yields tensors 
        representing shards of text cooccurrence data.  Each shard has unigram
        and cooccurrence data, for words and word-pairs, along with totals.

        cooccurrence data:
            `Nxx`   number of times ith word seen with jth word.
            `Nx`    marginalized (summed) counts: num pairs containing ith word
            `Nxt`   marginalized (summed) counts: num pairs containing jth word
            `N`     total number of pairs.

            Note: marginalized counts aren't equal to frequency of the word,
            one word occurrence means participating in ~2 x window-size number
            of pairs.

        unigram data `(uNx, uNxt, uN)`
            `uNx`   Number of times word i occurs.
            `uNxt`  Number of times word j occurs.
            `uN`    total number of words

            Note: Due to unigram-smoothing (e.g. in w2v), uNxt may not equal
            uNx.  In w2v, one gets smoothed, the other is left unchanged (both
            are needed).
        """
        super(DenseShardPreloader, self).__init__(
            cooccurrence_path, t_clean_undersample=t_clean_undersample,
            alpha_unigram_smoothing=alpha_unigram_smoothing
        )
        self.sector_factor = sector_factor
        self.shard_factor = shard_factor
        self.cooccurrence_sector = None
        self.verbose = verbose


    def preload_iter(self, *args, **kwargs):
        super(DenseShardPreloader, self).preload_iter(*args, **kwargs)

        for i, sector_id in enumerate(h.shards.Shards(self.sector_factor)):
            if self.verbose:
                print('loading sector {}'.format(i))

            # Read the sector of cooccurrence data into memory, and transform
            # distributions as desired.
            self.cooccurrence_sector = h.cooccurrence.CooccurrenceSector.load(
                self.cooccurrence_path, sector_id)

            self.cooccurrence_sector.apply_w2v_undersampling(
                self.t_clean_undersample)

            self.cooccurrence_sector.apply_unigram_smoothing(
                self.alpha_unigram_smoothing)

            # Start yielding cRAM-preloaded shards
            for shard_id in h.shards.Shards(self.shard_factor):

                cooccurrence_data = self.cooccurrence_sector.load_relative_shard(
                    shard=shard_id, device='cpu')

                unigram_data = self.cooccurrence_sector.load_relative_unigram_shard(
                    shard=shard_id, device='cpu')

                yield shard_id * sector_id, cooccurrence_data, unigram_data
        return


    def describe(self):
        s = super(DenseShardPreloader, self).describe()
        s += 'Dense Preloader\n'
        s += '\tsector_factor = {}\n'.format(self.sector_factor)
        s += '\tshard_factor = {}\n'.format(self.shard_factor)
        return s





class TupSparsePreloader(BatchPreloader):
    """
    Class for smart compressed data loading & iteration.
    A somewhat data-inefficient class for compressed representation.
    But very very parallelizable on GPU.
    """

    def __init__(
            self, cooccurrence_path,
            t_clean_undersample=None,
            alpha_unigram_smoothing=None,
            zk=1000,
            n_batches=1000,
            include_unigram_data=False,
            filter_repeats=False,
            device=None
        ):
        super(TupSparsePreloader, self).__init__(
            cooccurrence_path, t_clean_undersample=t_clean_undersample,
            alpha_unigram_smoothing=alpha_unigram_smoothing,
        )
        self.zk = zk # max number of z-samples to draw
        self.include_unigram_data = include_unigram_data
        self.filter_repeats = filter_repeats
        self.device = device

        # put the other attributes in init for transparency
        self.n_batches = n_batches
        self.n_nonzeros = 0
        self.batch_size = None
        self.z_sampler = None
        self.sparse_nxx = None
        self.Nx, self.Nxt, self.N = None, None, None
        self.uNx, self.uNxt, self.uN = None, None, None


    def preload_iter(self, *args, **kwargs):
        super(TupSparsePreloader, self).preload_iter(*args, **kwargs)

        cooccurrence = h.cooccurrence.Cooccurrence.load(
            self.cooccurrence_path, marginalize=False)
        self.n_nonzeros = cooccurrence.Nxx.nnz

        # Iterate over each row index in the sparse matrix
        data = build_sparse_tup_nxx(
            cooccurrence, self.include_unigram_data, self.device)
        self.xx, self.nxx = data[0]
        self.Nx, self.Nxt, self.N = data[1]
        self.uNx, self.uNxt, self.uN = data[2]

        # Number of nonzero elements; upper limit is the vocab size
        self.z_sampler = ZedSampler(
            len(self.Nx), self.device, self.zk,
            filter_repeats=self.filter_repeats
        )

        # store the preloaded batches as a list of slices
        self.batch_size = int(ceil(len(self.xx[0]) / self.n_batches))
        for batch in range(self.n_batches):
            yield slice( batch * self.batch_size,
                         (batch + 1) * self.batch_size )
        return


    def prepare(self, preloaded_slice):
        # convert to long in order to grab slice,
        # but otherwise store as int to cut data usage in half!
        ij_tensor = self.xx[:, preloaded_slice].long()

        # get the Nij=0 random samples and concat
        zij, zeds = self.z_sampler.z_sample(ij_tensor.t(), shape=2)
        ij_tensor = torch.cat((ij_tensor, zij.t()), dim=1)
        all_nij = torch.cat((self.nxx[preloaded_slice], zeds))

        # prepare the data for learning
        cooccurrence_data = (all_nij,
                       self.Nx[ij_tensor[0]],
                       self.Nxt[ij_tensor[1]],
                       self.N)

        # fill up unigram data only if necessary
        unigram_data = None
        if self.include_unigram_data:
            unigram_data = (self.uNx[ij_tensor[0]],
                            self.uNxt[ij_tensor[1]],
                            self.uN)

        # batch_id is the ij_tensor
        return ij_tensor, cooccurrence_data, unigram_data


    def describe(self):
        s = super(TupSparsePreloader, self).describe()
        s += 'Tuple-based Sparse preloader\n'
        s += '\tzk = {}\n'.format(self.zk)
        s += '\tfilter repeats = {}\n'.format(self.filter_repeats)
        s += '\tinclude unigram data = {}\n'.format(self.include_unigram_data)
        s += '\tnumber of nonzero nijs = {}\n'.format(self.n_nonzeros)
        s += '\tn batches = {}\n'.format(self.n_batches)
        s += '\tbatch size = {}\n'.format(self.batch_size)
        return s



"""
Class for compressed data loading & iteration.
"""
class LilSparsePreloader(BatchPreloader):

    def __init__(
            self, cooccurrence_path,
            t_clean_undersample=None,
            alpha_unigram_smoothing=None,
            zk=1000,
            include_unigram_data=False,
            filter_repeats=False,
            device=None
        ):
        super(LilSparsePreloader, self).__init__(
            cooccurrence_path, t_clean_undersample=t_clean_undersample,
            alpha_unigram_smoothing=alpha_unigram_smoothing,
        )
        self.zk = zk # max number of z-samples to draw
        self.include_unigram_data = include_unigram_data
        self.filter_repeats = filter_repeats
        self.device = device

        # put the other attributes in init for transparency
        self.n_nonzeros = 0
        self.n_batches = 0
        self.z_sampler = None
        self.sparse_nxx = None
        self.Nx, self.Nxt, self.N = None, None, None
        self.uNx, self.uNxt, self.uN = None, None, None


    def preload_iter(self, *args, **kwargs):
        super(LilSparsePreloader, self).preload_iter(*args, **kwargs)

        cooccurrence = h.cooccurrence.Cooccurrence.load(self.cooccurrence_path, marginalize=False)

        # Number of nonzero elements
        self.n_nonzeros = cooccurrence.Nxx.nnz

        # Number of batches, equivalent to vocab size
        self.n_batches = len(cooccurrence.Nxx.data)
        self.z_sampler = ZedSampler(
            self.n_batches, self.device, self.zk,
            filter_repeats=self.filter_repeats
        )

        # Iterate over each row index in the sparse matrix
        data = build_sparse_lil_nxx(cooccurrence, self.include_unigram_data, self.device)
        self.sparse_nxx = data[0]
        self.Nx, self.Nxt, self.N = data[1]
        self.uNx, self.uNxt, self.uN = data[2]

        # implicitly store the preloaded batches
        return range(self.n_batches)


    def prepare(self, preloaded):
        # alpha-samples are the js
        i, js = preloaded, self.sparse_nxx[preloaded][0]

        # zed-samples
        z_js, z_nijs = self.z_sampler.z_sample(js, shape=1)
        all_js = torch.cat((js, z_js))
        all_nxx = torch.cat((self.sparse_nxx[preloaded][1], z_nijs))

        # prepare the data for learning
        cooccurrence_data = (all_nxx,
                       self.Nx[i],
                       self.Nxt[all_js],
                       self.N)

        # fill up unigram data only if necessary
        unigram_data = None
        if self.include_unigram_data:
            unigram_data = (self.uNx[i], self.uNxt[all_js], self.uN)

        batch_id = (i, all_js)
        return batch_id, cooccurrence_data, unigram_data


    def describe(self):
        s = super(LilSparsePreloader, self).describe()
        s += 'Linked-List-based Sparse preloader\n'
        s += '\tzk = {}\n'.format(self.zk)
        s += '\tfilter repeats = {}\n'.format(self.filter_repeats)
        s += '\tnumber of nonzero nijs = {}\n'.format(self.n_nonzeros)
        s += '\tinclude unigram data = {}\n'.format(self.include_unigram_data)
        return s



"""
Utility class for Z-sampling on the GPU.
"""
class ZedSampler(object):

    def __init__(self, upper_limit, device, max_z_samples=1000, filter_repeats=False):
        self.max_z_samples = max_z_samples
        self.upper_limit = upper_limit
        self.device = device
        self.zeds = torch.zeros((max_z_samples,), device=device).float()
        self.filter_repeats = filter_repeats


    def z_sample(self, a_samples, shape=1):
        """
        We can expect approximately 1% of the uniform random samples to
        be repeats from the alpha-samples. If you don't mind your loss to be
        noisy (perhaps it could even work as regularization), and you want
        to draw samples at constant time, then pass filter_repeats=False.

        Otherwise, it averages at about .18s to draw 10,000
        Z-samples with filter_repeats=True, and only .018s for 1,000.
        Both of these are much much too time consuming, so do not do this.
        (E.g., if vocab is O(10^5), then drawing 10,000 will require
        approximately 5 hours per epoch just for doing this.)

        If vocab size is O(10^5) and we are drawing O(10^3) samples, we can
        be almost certain that there will be no repeats, so use
        filter_repeats=False when max_z_samples=1000.

        :param a_samples: tensor of the Nij > 0 samples that we are comparing against
        :param filter_repeats: parameter of whether or not we want to filter
            out the repeated samples, if we do we are true to the real loss.
        :return: tensor of Z-samples with Nij=0
                (99.99% chance that Nij=0 if filter_repeats=False)
        """

        # sort the samples and grab the values, [0] (args are in [1]
        num_zeds = min(len(a_samples), self.max_z_samples)
        size = (num_zeds,) if shape == 1 else (num_zeds, shape)
        samples = torch.randint(self.upper_limit,
                                device=self.device,
                                size=size).long()

        if not self.filter_repeats:
            return samples, self.zeds[:num_zeds]
        else:
            samples = samples.sort()[0]

        # filter so we don't have repeats, taking advantage of the fact
        # that both sets are sorted.
        bits = torch.ones((len(samples),), device=samples.device, dtype=torch.uint8)
        a_idx = 0 # torch.LongTensor([0], device=samples.device)[0]
        s_idx = 0 # torch.LongTensor([0], device=samples.device)[0]

        # TODO: fix algorithm so that it properly handles when the same value is repeated.
        try:
            while True:

                while samples[s_idx] != a_samples[a_idx]:

                    while samples[s_idx] < a_samples[a_idx]:
                        s_idx += 1

                    while a_samples[a_idx] < samples[s_idx]:
                        a_idx += 1

                bits[s_idx] = 0
                s_idx += 1
                a_idx += 1

        except IndexError:
            pass

        good_samples = samples[bits.nonzero().flatten()]
        return good_samples, self.zeds[:len(good_samples)]


