import os
import sys
import random
import codecs
import argparse
import itertools
from collections import Counter
import time
import numpy as np
import hilbert as h
import shared
from multiprocessing import Pool
from multiprocessing.managers import BaseManager



# TODO: test min_count and vocab


def extract_unigram(corpus_path, unigram, verbose=True):
    """
    Slowly accumulate the vocabulary and unigram statistics for the corpus
    path at ``corpus_path``, and using the provided ``unigram`` instance.

    To do this more quickly using parallelization, use 
    ``extract_unigram_parallel`` instead.
    """
    with open(corpus_path) as corpus_f:
        start = time.time()
        for line_num, line in enumerate(corpus_f):
            if verbose and line_num % 1000 == 0:
                sys.stdout.write(
                    '\rTime elapsed: %0.f sec.;  '
                    'Lines read (in one process): %d'
                    % (time.time() - start, line_num)
                )
            tokens = line.strip().split()
            for token in tokens:
                unigram.add(token)
    if verbose:
        print()
    unigram.sort()


def extract_unigram_parallel(
    corpus_path, processes, save_path=None, verbose=True
):
    """
    Accumulate the vocabulary and unigram statistics for the corpus
    path at ``corpus_path``, by parallelizing across ``processes`` processes.
    Optionally save the unigram statistics to the directory ``save_path``
    (making it if it doesn't exist).
    """
    pool = Pool(processes)
    args = (
        (corpus_path, worker_id, processes, verbose) 
        for worker_id in range(processes)
    )
    unigrams = pool.map(extract_unigram_parallel_worker, args)
    unigram = sum(unigrams, h.unigram.Unigram())
    if save_path is not None:
        unigram.save(save_path)
    return unigram


def extract_unigram_parallel_worker(args):
    corpus_path, worker_id, processes, verbose = args
    unigram = h.unigram.Unigram()
    file_chunk = h.file_access.open_chunk(corpus_path, worker_id, processes)
    start = time.time()
    for line_num, line in enumerate(file_chunk):
        if worker_id == 0 and verbose and line_num % 1000 == 0:
            sys.stdout.write(
                '\rTime elapsed: %0.f sec.;  '
                'Lines read (in one process): %d'
                % (time.time() - start, line_num)
            )
        tokens = line.strip().split()
        for token in tokens:
            unigram.add(token)
    if worker_id == 0 and verbose:
        print()
    return unigram



def extract_cooccurrence(corpus_path, extractor, verbose=True):
    """
    Slowly extracts cooccurrence statistics from ``corpus_path`` using
    the ``Extractor`` instance ``extractor``.

    The input file should be space-tokenized, and normally should have one
    document per line.  Cooccurrences are only considered within the same line
    (i.e. words on different lines aren't considered as cooccurring no matter
    how close together they are).

    To do this more quickly using parallelization, use
    ``extract_cooccurrence_parallel`` instead.
    """
    with codecs.open(corpus_path, 'r', errors='replace') as in_file:
        start = time.time()
        for line_num, line in enumerate(in_file):
            if verbose and line_num % 1000 == 0:
                sys.stdout.write(
                    '\rTime elapsed: %0.f sec.;  '
                    'Lines read (in one process): %d'
                    % (time.time() - start, line_num)
                )
            extractor.extract(line.split())
    if verbose:
        print()




def extract_cooccurrence_parallel(
    corpus_path, processes, unigram, 
    extractor_str, window=None, min_count=None, 
    weights=None, save_path=None, verbose=True
):
    pool = Pool(processes)
    extractor_constructor_args = {
        'extractor_str': extractor_str, 
        'window': window,
        'min_count': min_count,
        'weights': weights,
    }
    args = (
        (
            corpus_path, worker_id, processes, unigram,
            extractor_constructor_args, verbose
        ) 
        for worker_id in range(processes)
    )
    cooccurrence = pool.map(extract_cooccurrence_parallel_worker, args)

    merged_cooccurrence = cooccurrence[0]
    for _cooccurrence in cooccurrence[1:]:
        merged_cooccurrence.merge(_cooccurrence)

    if save_path is not None:
        merged_cooccurrence.save(save_path)
    return merged_cooccurrence




def extract_cooccurrence_parallel_worker(args):
    (
        corpus_path, worker_id, processes, unigram, 
        extractor_constructor_args, verbose
    ) = args
    cooccurrence = h.cooccurrence.CooccurrenceMutable(unigram)
    extractor = h.cooccurrence.extractor.get_extractor(
        cooccurrence=cooccurrence, **extractor_constructor_args)
    file_chunk = h.file_access.open_chunk(corpus_path, worker_id, processes)
    start = time.time()
    for line_num, line in enumerate(file_chunk):
        if worker_id == 0 and verbose and line_num % 1000 == 0:
            sys.stdout.write(
                '\rTime elapsed: %0.f sec.;  '
                'Lines read (in one process): %d'
                % (time.time() - start, line_num)
            )
        extractor.extract(line.split())
    if worker_id == 0 and verbose:
        print()
    return cooccurrence


def reproduce_error():
    processes = 2
    manager = CooccurrenceManager()
    manager.start()
    sharables = [manager.Sharable(), manager.Sharable()]
    pool = Pool(processes)
    args = [sharables[0], sharables[1]]
    import pdb; pdb.set_trace()
    results = pool.map(reproduce_error_worker, args)
    for result in results:
        print('ok')

    import pdb; pdb.set_trace()



class Sharable:
    def __int__(self):
        self.array = None
    def make(self):
        self.array = np.random.random((20000,20000))


class CooccurrenceManager(BaseManager):
    pass
CooccurrenceManager.register('Sharable', Sharable, exposed=['make', 'array'])


def reproduce_error_worker(sharable):
    sharable.make()
    #return np.random.random((20000,20000))







def l(s):
    """lengthen the string `s`."""
    return s.ljust(12, ' ')


def extract_unigram_and_cooccurrence(
    corpus_path,
    save_path,
    extractor_str,
    window=None,
    weights=None,
    processes=1,
    min_count=None,
    vocab=None,
    verbose=True
):

    if verbose:
        print()
        print(l('Processes:'), processes)
        print(l('Corpus:'), corpus_path)
        print(l('Output:'), save_path)
        print(l('Extractor:'),extractor_str)
        print(l('Weights:'), weights)
        print(l('Window:'), window)

    # Attempt to read unigram, if none exists, then train it and save to disc.
    try:

        if verbose:
            sys.stdout.write('\nAttempting to read unigram data...')
        unigram = h.unigram.Unigram.load(save_path)
        if vocab is not None and len(unigram) > vocab:
            raise ValueError(
                'An existing unigram object was found on disk, having a '
                'vocabulary size of {}, but a vocabulary size of {} was '
                'requested.  Either truncate it manually, or run extraction '
                'for existing vocabulary size.'.format(len(unigram), vocab)
            )
        elif min_count is not None and min(unigram.Nx) < min_count:
            raise ValueError(
                'An existing unigram object was found on disk, containing '
                'tokens occuring only {} times (less than the requested '
                'min_count of {}).  Either prune it manually, or run '
                'extraction with `min_count` reduced.'.format(
                    min(unigram.Nx), min_count))
        elif verbose:
            print('Found.')

    except IOError:
        if verbose:
            print('None found.  Collecting unigram data...')
        unigram = extract_unigram_parallel(
            corpus_path, processes, verbose=verbose)
        if vocab is not None:
            unigram.truncate(vocab)
        if min_count is not None:
            unigram.prune(min_count)

        if verbose:
            print('Saving unigram data...')
        unigram.save(save_path)

    # Extract the cooccurrence, and save it to disc.
    if verbose:
        print('\nCollecting cooccurrence data...')
    cooccurrence = extract_cooccurrence_parallel(
        corpus_path=corpus_path, processes=processes, unigram=unigram,
        extractor_str=extractor_str, window=window,
        min_count=min_count, weights=weights, save_path=save_path,
        verbose=verbose
    )
    if verbose:
        print('\nSaving cooccurrence data...')
    cooccurrence.save(save_path)

