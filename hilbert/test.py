import os
import shutil
from unittest import main, TestCase
from copy import copy, deepcopy
from scipy import sparse
from collections import Counter
import numpy as np
import hilbert as h
import torch


class TestCorpusStats(TestCase):

    UNIQUE_TOKENS = {
    '.': 5, 'Drive': 3, 'Eat': 7, 'The': 10, 'bread': 0, 'car': 6,
    'has': 8, 'sandwich': 9, 'spin': 4, 'the': 1, 'wheels': 2
    }
    N_XX_2 = np.array([
		[0, 12, 23, 8, 8, 8, 8, 12, 7, 4, 4], 
		[12, 0, 0, 8, 8, 0, 8, 8, 0, 0, 4], 
		[23, 0, 0, 4, 0, 4, 4, 0, 8, 4, 0], 
		[8, 8, 4, 0, 4, 4, 0, 0, 4, 0, 0], 
		[8, 8, 0, 4, 0, 4, 4, 4, 0, 0, 0], 
		[8, 0, 4, 4, 4, 0, 0, 0, 11, 1, 0], 
		[8, 8, 4, 0, 4, 0, 0, 4, 0, 4, 0], 
		[12, 8, 0, 0, 4, 0, 4, 0, 0, 0, 4], 
		[7, 0, 8, 4, 0, 11, 0, 0, 0, 0, 0], 
		[4, 0, 4, 0, 0, 1, 4, 0, 0, 0, 3], 
		[4, 4, 0, 0, 0, 0, 0, 4, 0, 3, 0]
    ]) 

    N_XX_3 = np.array([
        [0, 16, 23, 16, 12, 16, 15, 12, 15, 8, 8],
        [16, 0, 8, 12, 4, 8, 8, 12, 0, 0, 4],
        [23, 8, 0, 0, 12, 4, 4, 0, 11, 5, 3],
        [16, 12, 0, 0, 4, 4, 4, 4, 4, 0, 0],
        [12, 4, 12, 4, 0, 0, 4, 0, 11, 1, 0],
        [16, 8, 4, 4, 0, 8, 0, 4, 0, 4, 0],
        [15, 8, 4, 4, 4, 0, 8, 0, 4, 0, 0],
        [12, 12, 0, 4, 0, 4, 0, 8, 0, 3, 4],
        [15, 0, 11, 4, 11, 0, 4, 0, 0, 0, 0],
        [8, 0, 5, 0, 1, 4, 0, 3, 0, 0, 3],
        [8, 4, 3, 0, 0, 0, 0, 4, 0, 3, 0],
    ])


    def test_PMI(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        expected_PMI = np.load('test-data/expected_PMI.npz')['arr_0']
        found_PMI = h.corpus_stats.calc_PMI(cooc_stats)
        self.assertTrue(np.allclose(found_PMI, expected_PMI))


    def test_calc_positive_PMI(self):
        expected_positive_PMI = np.load('test-data/expected_PMI.npz')['arr_0']
        expected_positive_PMI[expected_positive_PMI < 0] = 0
        cooc_stats = h.corpus_stats.get_test_stats(2)
        found_positive_PMI = h.corpus_stats.calc_positive_PMI(cooc_stats)
        self.assertTrue(np.allclose(found_positive_PMI, expected_positive_PMI))


    def test_calc_shifted_PMI(self):
        k = 15.0
        cooc_stats = h.corpus_stats.get_test_stats(2)
        expected_PMI = np.load('test-data/expected_PMI.npz')['arr_0']
        expected_shifted_PMI = expected_PMI - np.log(k)
        found = h.corpus_stats.calc_shifted_w2v_PMI(k, cooc_stats)
        self.assertTrue(np.allclose(found, expected_shifted_PMI))


    def test_get_stats(self):
        # Next, test with a cooccurrence window of +/-2
        cooc_stats = h.corpus_stats.get_test_stats(2)
        self.assertTrue(np.allclose(cooc_stats.Nxx.toarray(),self.N_XX_2))

        # Next, test with a cooccurrence window of +/-3
        cooc_stats = h.corpus_stats.get_test_stats(3)
        self.assertTrue(np.allclose(cooc_stats.Nxx.toarray(),self.N_XX_3))




class TestFDeltas(TestCase):


    def test_sigmoid(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        PMI = h.corpus_stats.calc_PMI(cooc_stats)
        expected = np.array([
            [1/(1+np.e**(-pmi)) for pmi in row]
            for row in PMI
        ])
        result = np.zeros(PMI.shape)
        h.f_delta.sigmoid(PMI, result)
        self.assertTrue(np.allclose(expected, result))



    def test_N_xx_neg(self):
        k = 15.0
        cooc_stats = h.corpus_stats.get_test_stats(2)
        expected = k * cooc_stats.Nx * cooc_stats.Nx.T / cooc_stats.N
        found = h.f_delta.calc_N_neg_xx(k, cooc_stats.Nx)
        self.assertTrue(np.allclose(expected, found))



    def test_f_w2v(self):
        k = 15
        cooc_stats = h.corpus_stats.get_test_stats(2)

        M = h.corpus_stats.calc_PMI(cooc_stats) - np.log(k)
        M_hat = M + 1
        N_neg_xx = h.f_delta.calc_N_neg_xx(k, cooc_stats.Nx)

        difference = h.f_delta.sigmoid(M) - h.f_delta.sigmoid(M_hat)
        multiplier = N_neg_xx + cooc_stats.Nxx.toarray()
        expected = multiplier * difference

        delta = np.zeros(M.shape)
        f_w2v = h.f_delta.get_f_w2v(cooc_stats, k)
        found = f_w2v(M, M_hat, delta)

        self.assertTrue(np.allclose(expected, found))


    def test_f_glove(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        with np.errstate(divide='ignore'):
            M = np.log(cooc_stats.Nxx.toarray())
        M_hat = M_hat = M - 1
        expected = np.array([
            [
                2 * min(1, (cooc_stats.Nxx[i,j] / 100.0)**0.75) 
                    * (M[i,j] - M_hat[i,j])
                if cooc_stats.Nxx[i,j] > 0 else 0 
                for j in range(cooc_stats.Nxx.shape[1])
            ]
            for i in range(cooc_stats.Nxx.shape[0])
        ])

        delta = np.zeros(M.shape)
        f_glove = h.f_delta.get_f_glove(cooc_stats)
        found = f_glove(M, M_hat, delta)

        self.assertTrue(np.allclose(expected, found))
        f_glove = h.f_delta.get_f_glove(cooc_stats, 10)
        found2 = f_glove(M, M_hat, delta)

        expected2 = np.array([
            [
                2 * min(1, (cooc_stats.Nxx[i,j] / 10.0)**0.75) 
                    * (M[i,j] - M_hat[i,j])
                if cooc_stats.Nxx[i,j] > 0 else 0 
                for j in range(cooc_stats.Nxx.shape[1])
            ]
            for i in range(cooc_stats.Nxx.shape[0])
        ])
        self.assertTrue(np.allclose(expected2, found2))
        self.assertFalse(np.allclose(expected2, expected))


    def test_f_mse(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        M_hat = M + 1
        expected = M - M_hat
        delta = np.zeros(M.shape)
        found = h.f_delta.f_mse(M, M_hat, delta)
        np.testing.assert_equal(expected, found)


    def test_calc_M_swivel(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        # Destructively put ones wherever Nxx is zero.  Don't try this at home.
        # It's a hack to easily calculate the PMI-star
        cooc_stats.Nxx[cooc_stats.Nxx == 0] = 1
        PMI_star = h.corpus_stats.calc_PMI(cooc_stats)
        found = h.f_delta.calc_M_swivel(cooc_stats)
        self.assertTrue(np.allclose(found, PMI_star))


    def test_f_swivel(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.f_delta.calc_M_swivel(cooc_stats)
        M_hat = M + 1
        expected = np.array([
            [
                np.sqrt(cooc_stats.Nxx[i,j]) * (M[i,j] - M_hat[i,j]) 
                if cooc_stats.Nxx[i,j] > 0 else
                (np.e**(M[i,j] - M_hat[i,j]) /
                    (1 + np.e**(M[i,j] - M_hat[i,j])))
                for j in range(M.shape[1])
            ]
            for i in range(M.shape[0])
        ])
        delta = np.zeros(M.shape)
        f_swivel = h.f_delta.get_f_swivel(cooc_stats)
        found = f_swivel(M, M_hat, delta)
        self.assertTrue(np.allclose(found, expected))


    def test_f_MLE(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_PMI(cooc_stats)
        M_hat = M + 1

        N_indep_xx = cooc_stats.Nx * cooc_stats.Nx.T
        N_indep_max = np.max(N_indep_xx)

        expected = N_indep_xx / N_indep_max * (np.e**M - np.e**M_hat)

        delta = np.zeros(M.shape)
        f_MLE = h.f_delta.get_f_MLE(cooc_stats)
        found = f_MLE(M, M_hat, delta)
        self.assertTrue(np.allclose(found, expected))

        t = 10
        expected = (N_indep_xx / N_indep_max)**(1.0/t) * (
            np.e**M - np.e**M_hat)
        found = f_MLE(M, M_hat, delta, t=t)
        self.assertTrue(np.allclose(found, expected))


    def test_torch_f_MLE(self):
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = torch.tensor(
            h.corpus_stats.calc_PMI(cooc_stats), dtype=torch.float32)
        M_hat = M + 1

        N_indep_xx = torch.tensor(
            cooc_stats.Nx * cooc_stats.Nx.T, dtype=torch.float32)
        N_indep_max = torch.max(N_indep_xx)

        expected = N_indep_xx / N_indep_max * (np.e**M - np.e**M_hat)

        delta = np.zeros(M.shape)
        f_MLE = h.f_delta.get_torch_f_MLE(cooc_stats, M)
        found = f_MLE(M, M_hat)
        self.assertTrue(np.allclose(found, expected))

        t = 10
        expected = (N_indep_xx / N_indep_max)**(1.0/t) * (
            np.e**M - np.e**M_hat)
        found = f_MLE(M, M_hat, t=t)
        self.assertTrue(np.allclose(found, expected))




class TestConstrainer(TestCase):

    def test_glove_constrainer(self):
        W, V = np.zeros((3,3)), np.zeros((3,3))
        h.constrainer.glove_constrainer(W, V)
        self.assertTrue(np.allclose(W, np.array([[0,1,0]]*3)))
        self.assertTrue(np.allclose(V, np.array([[1,0,0]]*3).T))





class TestHilbertEmbedder(TestCase):

    def test_integration_with_constrainer(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Define an arbitrary f_delta
        # First make a non-one-sided embedder.
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate,
            constrainer=h.constrainer.glove_constrainer
        )

        old_V = embedder.V.copy()
        old_W = embedder.W.copy()

        embedder.cycle(print_badness=False)

        # Check that the update was performed, and constraints applied.
        new_V = old_V + learning_rate * np.dot(old_W.T, M - embedder.M_hat)
        new_W = old_W + learning_rate * np.dot(M - embedder.M_hat, old_V.T)
        h.constrainer.glove_constrainer(new_W, new_V)
        self.assertTrue(np.allclose(embedder.V, new_V))
        self.assertTrue(np.allclose(embedder.W, new_W))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        embedder.calc_badness()
        badness = np.sum(abs(M - np.dot(old_W, old_V))) / (d*d)
        self.assertEqual(badness, embedder.badness)



    def test_get_gradient(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)

        W, V = embedder.W.copy(), embedder.V.copy()
        M_hat = np.dot(W,V)
        delta = M - M_hat
        expected_nabla_W = np.dot(delta, V.T)
        expected_nabla_V = np.dot(W.T, delta)

        nabla_V, nabla_W = embedder.get_gradient()

        self.assertTrue(np.allclose(nabla_W, expected_nabla_W))
        self.assertTrue(np.allclose(nabla_V, expected_nabla_V))


    def test_get_gradient_with_offsets(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        offset_W = np.random.random(cooc_stats.Nxx.shape)
        offset_V = np.random.random(cooc_stats.Nxx.shape)
        
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)

        original_W, original_V = embedder.W.copy(), embedder.V.copy()
        W, V =  original_W + offset_W,  original_V + offset_V
        M_hat = np.dot(W,V)
        delta = M - M_hat
        expected_nabla_W = np.dot(delta, V.T)
        expected_nabla_V = np.dot(W.T, delta)

        nabla_V, nabla_W = embedder.get_gradient(offsets=(offset_V, offset_W))

        self.assertTrue(np.allclose(nabla_W, expected_nabla_W))
        self.assertTrue(np.allclose(nabla_V, expected_nabla_V))

        # Verify that the embeddings were not altered by the offset
        self.assertTrue(np.allclose(original_W, embedder.W))
        self.assertTrue(np.allclose(original_V, embedder.V))


    def test_get_gradient_one_sided(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate, one_sided=True)

        original_V = embedder.V.copy()
        V =  original_V
        M_hat = np.dot(V.T,V)
        delta = M - M_hat
        expected_nabla_V = np.dot(V, delta)

        nabla_V = embedder.get_gradient()

        self.assertTrue(np.allclose(nabla_V, expected_nabla_V))

        # Verify that the embeddings were not altered by the offset
        self.assertTrue(np.allclose(original_V.T, embedder.W))
        self.assertTrue(np.allclose(original_V, embedder.V))


    def test_get_gradient_one_sided_with_offset(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        offset_V = np.random.random(cooc_stats.Nxx.shape)
        
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate, one_sided=True)

        original_V = embedder.V.copy()
        V =  original_V + offset_V
        M_hat = np.dot(V.T,V)
        delta = M - M_hat
        expected_nabla_V = np.dot(V, delta)

        nabla_V = embedder.get_gradient(offsets=offset_V)

        self.assertTrue(np.allclose(nabla_V, expected_nabla_V))

        # Verify that the embeddings were not altered by the offset
        self.assertTrue(np.allclose(original_V.T, embedder.W))
        self.assertTrue(np.allclose(original_V, embedder.V))



    def test_integration_with_f_delta(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        pass_args = {'a':True, 'b':False}

        def mock_f_delta(M_, M_hat_, delta_, **kwargs):
            self.assertTrue(M_ is M)
            self.assertEqual(kwargs, {'a':True, 'b':False})
            return np.subtract(M_, M_hat_, delta_)

        embedder = h.embedder.HilbertEmbedder(
            M, d, mock_f_delta, learning_rate, pass_args=pass_args)

        self.assertEqual(embedder.learning_rate, learning_rate)
        self.assertEqual(embedder.d, d)
        self.assertTrue(embedder.M is M)
        self.assertEqual(embedder.f_delta, mock_f_delta)

        old_W, old_V = embedder.W.copy(), embedder.V.copy()

        embedder.cycle(pass_args=pass_args, print_badness=False)

        # Check that the update was performed
        new_V = old_V + learning_rate * np.dot(old_W.T, embedder.delta)
        new_W = old_W + learning_rate * np.dot(embedder.delta, old_V.T)
        self.assertTrue(np.allclose(embedder.V, new_V))
        self.assertTrue(np.allclose(embedder.W, new_W))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        embedder.calc_badness()
        badness = np.sum(abs(M - np.dot(old_W, old_V))) / (d*d)
        self.assertEqual(badness, embedder.badness)


    def test_arbitrary_f_delta(self):
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Define an arbitrary f_delta
        delta_amount = 0.1
        delta_always = np.zeros(M.shape) + delta_amount
        def f_delta(M, M_hat, delta):
            delta[:,:] = delta_amount
            return delta

        # First make a non-one-sided embedder.
        embedder = h.embedder.HilbertEmbedder(M, d, f_delta, learning_rate)

        old_V = embedder.V.copy()
        old_W = embedder.W.copy()

        embedder.cycle(print_badness=False)

        # Check that the update was performed.  Notice that the update of W
        # uses the old value of V, hence a synchronous update.
        new_V = old_V + learning_rate * np.dot(old_W.T, delta_always)
        new_W = old_W + learning_rate * np.dot(delta_always, old_V.T)
        self.assertTrue(np.allclose(embedder.V, new_V))
        self.assertTrue(np.allclose(embedder.W, new_W))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        embedder.calc_badness()
        badness = np.sum(delta_always) / (d*d)
        self.assertEqual(badness, embedder.badness)


    def test_one_sided(self):
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # First make a non-one-sided embedder.
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate
        )

        # The covectors and vectors are not the same.
        self.assertFalse(np.allclose(embedder.W, embedder.V.T))

        # Now make a one-sided embedder.
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate, one_sided=True
        )

        # The covectors and vectors are the same.
        self.assertTrue(np.allclose(embedder.W, embedder.V.T))

        old_V = embedder.V.copy()
        embedder.cycle(print_badness=False)

        # Check that the update was performed.
        new_V = old_V + learning_rate * np.dot(old_V, embedder.delta)
        self.assertTrue(np.allclose(embedder.V, new_V))

        # Check that the vectors and covectors are still identical after the
        # update.
        self.assertTrue(np.allclose(embedder.W, embedder.V.T))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        embedder.calc_badness()
        badness = np.sum(abs(M - np.dot(old_V.T, old_V))) / (d*d)
        self.assertEqual(badness, embedder.badness)


    def test_mse_embedder(self):
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        mse_embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)
        mse_embedder.cycle(100000, print_badness=False)

        self.assertEqual(mse_embedder.V.shape, (M.shape[1],d))
        self.assertEqual(mse_embedder.W.shape, (d,M.shape[0]))

        delta = np.zeros(M.shape, dtype='float64')
        residual = h.f_delta.f_mse(M, mse_embedder.M_hat, delta)

        self.assertTrue(np.allclose(residual, delta))
        

    def test_update(self):

        d = 11
        learning_rate = 0.01
        cooc_stats= h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)

        old_W, old_V = embedder.W.copy(), embedder.V.copy()

        delta_V = np.random.random(M.shape)
        delta_W = np.random.random(M.shape)
        updates = delta_V, delta_W
        embedder.update(*updates)
        self.assertTrue(np.allclose(old_W + delta_W, embedder.W))
        self.assertTrue(np.allclose(old_V + delta_V, embedder.V))


    def test_update_with_constraints(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate,
            constrainer=h.constrainer.glove_constrainer
        )

        old_W, old_V = embedder.W.copy(), embedder.V.copy()

        delta_V = np.random.random(M.shape)
        delta_W = np.random.random(M.shape)
        updates = delta_V, delta_W
        embedder.update(*updates)

        expected_updated_W = old_W + delta_W
        expected_updated_V = old_V + delta_V
        h.constrainer.glove_constrainer(expected_updated_W, expected_updated_V)

        self.assertTrue(np.allclose(expected_updated_W, embedder.W))
        self.assertTrue(np.allclose(expected_updated_V, embedder.V))



    def test_update_one_sided_rejects_delta_W(self):

        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)

        # Show that we can update covector embeddings for a non-one-sided model
        delta_W = np.ones(M.shape)
        embedder.update(delta_W=delta_W)

        # Now show that a one-sided embedder rejects updates to covectors
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate, one_sided=True)
        delta_W = np.ones(M.shape)
        with self.assertRaises(ValueError):
            embedder.update(delta_W=delta_W)



class TestTorchHilbertEmbedder(TestCase):


    def test_one_sided(self):
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # First make a non-one-sided embedder.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate
        )

        # Ensure that the relevant variables are tensors
        self.assertTrue(isinstance(embedder.V, torch.Tensor))
        self.assertTrue(isinstance(embedder.W, torch.Tensor))
        self.assertTrue(isinstance(embedder.M, torch.Tensor))


        # The covectors and vectors are not the same.
        self.assertFalse(torch.allclose(embedder.W, embedder.V.t()))

        # Now make a one-sided embedder.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate, one_sided=True
        )

        # Ensure that the relevant variables are tensors
        self.assertTrue(isinstance(embedder.V, torch.Tensor))
        self.assertTrue(isinstance(embedder.W, torch.Tensor))
        self.assertTrue(isinstance(embedder.M, torch.Tensor))

        # Now, the covectors and vectors are the same.
        self.assertTrue(torch.allclose(embedder.W, embedder.V.t()))

        old_V = embedder.V.clone()
        embedder.cycle(print_badness=False)

        self.assertTrue(isinstance(old_V, torch.Tensor))

        # Check that the update was performed.
        M_hat = torch.mm(old_V.t(), old_V)
        M = torch.tensor(M, dtype=torch.float32)
        delta = h.f_delta.torch_f_mse(M, M_hat)
        nabla_V = torch.mm(old_V, delta)
        new_V = old_V + learning_rate * nabla_V
        self.assertTrue(torch.allclose(embedder.V, new_V))

        # Check that the vectors and covectors are still identical after the
        # update.
        self.assertTrue(torch.allclose(embedder.W, embedder.V.t()))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        delta = abs(M - M_hat)
        badness = torch.sum(delta) / (d*d)
        self.assertEqual(badness, embedder.badness)



    def test_get_gradient(self):

        # Set up conditions for the test.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Make the embedder, whose method we are testing
        # Make the embedder, whose method we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate)

        # Take the random starting embeddings.  We will compute the gradient
        # manually here to see if it matches what the embedder's method
        # returns.
        W, V = embedder.W.clone(), embedder.V.clone()

        # Since we are not doing one-sided, W and V should be unrelated.
        self.assertFalse(torch.allclose(W.t(), V))

        # Calculate the expected gradient.
        M = torch.tensor(M, dtype=torch.float32)
        M_hat = torch.mm(W,V)
        delta = M - M_hat
        expected_nabla_W = torch.mm(delta, V.t())
        expected_nabla_V = torch.mm(W.t(), delta)

        # Get the gradient according to the embedder.
        nabla_V, nabla_W = embedder.get_gradient()

        # Embedder's gradients should match manually calculated expectation.
        self.assertTrue(torch.allclose(nabla_W, expected_nabla_W))
        self.assertTrue(torch.allclose(nabla_V, expected_nabla_V))


    def test_get_gradient_with_offsets(self):

        # Set up conditions for the test.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        offset_W = torch.rand(cooc_stats.Nxx.shape)
        offset_V = torch.rand(cooc_stats.Nxx.shape)

        # Create an embedder, whose get_gradient method we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate)

        # Manually calculate the gradients we expect, applying offsets to the
        # current embeddings first.
        original_W, original_V = embedder.W.clone(), embedder.V.clone()
        W, V =  original_W + offset_W,  original_V + offset_V
        M_hat = torch.mm(W,V)
        M = torch.tensor(M, dtype=torch.float32)
        delta = M - M_hat
        expected_nabla_W = torch.mm(delta, V.t())
        expected_nabla_V = torch.mm(W.t(), delta)

        # Get the gradient using the embedder's method
        nabla_V, nabla_W = embedder.get_gradient(offsets=(offset_V, offset_W))

        # Embedder gradients match values calculated here based on offsets.
        self.assertTrue(torch.allclose(nabla_W, expected_nabla_W))
        self.assertTrue(torch.allclose(nabla_V, expected_nabla_V))

        # Verify that the embeddings were not altered by the offset
        self.assertTrue(torch.allclose(original_W, embedder.W))
        self.assertTrue(torch.allclose(original_V, embedder.V))


    def test_get_gradient_one_sided(self):

        # Set up conditions for the test.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Make an embedder, whose get_gradient method we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate, one_sided=True)

        # Calculate the gradient manually here.
        original_V = embedder.V.clone()
        V = original_V
        M_hat = torch.mm(V.t(),V)
        M = torch.tensor(M, dtype=torch.float32)
        delta = M - M_hat
        expected_nabla_V = torch.mm(V, delta)

        # Get the gradient using the embedders method (which we are testing).
        nabla_V = embedder.get_gradient()

        # Gradient from embedder should match that manually calculated.
        self.assertTrue(torch.allclose(nabla_V, expected_nabla_V))

        # Verify that the embeddings were not altered by the offset
        self.assertTrue(torch.allclose(original_V.t(), embedder.W))
        self.assertTrue(torch.allclose(original_V, embedder.V))


    def test_get_gradient_one_sided_with_offset(self):

        # Set up test conditions.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        offset_V = torch.rand(cooc_stats.Nxx.shape)

        # Make an embedder, whose get_gradient method we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate, one_sided=True)

        # Manually calculate expected gradients
        original_V = embedder.V.clone()
        V =  original_V + offset_V
        M_hat = torch.mm(V.t(),V)
        M = torch.tensor(M, dtype=torch.float32)
        delta = M - M_hat
        expected_nabla_V = torch.mm(V, delta)

        # Calculate gradients using embedder's method (which we are testing).
        nabla_V = embedder.get_gradient(offsets=offset_V)

        # Gradients from embedder should match those calculated manuall.
        self.assertTrue(torch.allclose(nabla_V, expected_nabla_V))

        # Verify that the embeddings were not altered by the offset.
        self.assertTrue(torch.allclose(original_V.t(), embedder.W))
        self.assertTrue(torch.allclose(original_V, embedder.V))



    def test_integration_with_f_delta(self):

        # Set up conditions for test.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        pass_args = {'a':True, 'b':False}

        # Make mock f_delta whose integration with an embedder is being tested.
        def mock_torch_f_delta(M_, M_hat_, **kwargs):
            self.assertTrue(torch.allclose(
                M_, torch.tensor(M, dtype=torch.float32)))
            self.assertEqual(kwargs, {'a':True, 'b':False})
            return M_ - M_hat_

        # Make embedder whose integration with mock f_delta is being tested.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, mock_torch_f_delta, learning_rate, pass_args=pass_args)

        # Verify that all settings passed into the ebedder were registered,
        # and that the M matrix has been converted to a torch.Tensor.
        self.assertEqual(embedder.learning_rate, learning_rate)
        self.assertEqual(embedder.d, d)
        self.assertTrue(torch.allclose(
            embedder.M, torch.tensor(M, dtype=torch.float32)))
        self.assertEqual(embedder.f_delta, mock_torch_f_delta)

        # Clone current embeddings so we can manually calculate the expected
        # effect of one update cycle.
        old_W, old_V = embedder.W.clone(), embedder.V.clone()

        # Ask the embedder to progress through one update cycle.
        embedder.cycle(pass_args=pass_args, print_badness=False)

        # Calculate teh expected changes due to the update.
        M = torch.tensor(M, dtype=torch.float32)
        M_hat = torch.mm(old_W, old_V)
        delta = M - M_hat
        new_V = old_V + learning_rate * torch.mm(old_W.t(), delta)
        new_W = old_W + learning_rate * torch.mm(delta, old_V.t())

        # New embeddings in embedder should match manually updated ones.
        self.assertTrue(torch.allclose(embedder.V, new_V))
        self.assertTrue(torch.allclose(embedder.W, new_W))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        expected_badness = torch.sum(abs(M - torch.mm(old_W, old_V))) / (d*d)
        self.assertEqual(expected_badness, embedder.badness)


    def test_arbitrary_f_delta(self):
        # Set up conditions for test.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        delta_amount = 0.1

        # Test integration between an embedder and the following f_delta:
        delta_always = torch.zeros(M.shape) + delta_amount
        def f_delta(M, M_hat):
            return delta_always

        # Make the embedder whose integration with f_delta we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, f_delta, learning_rate)

        # Clone current embeddings to manually calculate expected update.
        old_V = embedder.V.clone()
        old_W = embedder.W.clone()

        # Ask the embedder to advance through an update cycle.
        embedder.cycle(print_badness=False)

        # Check that the update was performed.
        new_V = old_V + learning_rate * torch.mm(old_W.t(), delta_always)
        new_W = old_W + learning_rate * torch.mm(delta_always, old_V.t())
        self.assertTrue(torch.allclose(embedder.V, new_V))
        self.assertTrue(torch.allclose(embedder.W, new_W))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        expected_badness = torch.sum(delta_always) / (d*d)
        self.assertEqual(expected_badness, embedder.badness)


    def test_update(self):

        # Set up conditions for test.
        d = 11
        learning_rate = 0.01
        cooc_stats= h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Make the embedder whose update method we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate)

        # Generate some random update to be applied
        old_W, old_V = embedder.W.clone(), embedder.V.clone()
        delta_V = torch.rand(M.shape)
        delta_W = torch.rand(M.shape)
        updates = delta_V, delta_W

        # Apply the updates.
        embedder.update(*updates)

        # Verify that the embeddings moved by the provided amounts.
        self.assertTrue(torch.allclose(old_W + delta_W, embedder.W))
        self.assertTrue(torch.allclose(old_V + delta_V, embedder.V))


    def test_update_with_constraints(self):

        # Set up test conditions.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Make the ebedder whose integration with constrainer we are testing.
        # Note that we have included a constrainer.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate,
            constrainer=h.constrainer.glove_constrainer
        )

        # Clone the current embeddings, and apply a random update to them,
        # using the embedders update method.  Internally, the embedder should
        # apply the constraints after the update
        old_W, old_V = embedder.W.clone(), embedder.V.clone()
        delta_V = torch.rand(M.shape)
        delta_W = torch.rand(M.shape)
        updates = delta_V, delta_W
        embedder.update(*updates)

        # Calculate the expected updated embeddings, with application of
        # constraints.
        expected_updated_W = old_W + delta_W
        expected_updated_V = old_V + delta_V
        h.constrainer.glove_constrainer(expected_updated_W, expected_updated_V)

        # Verify that the resulting embeddings in the embedder match the ones
        # manually calculated here.
        self.assertTrue(torch.allclose(expected_updated_W, embedder.W))
        self.assertTrue(torch.allclose(expected_updated_V, embedder.V))

        # Verify that the contstraints really were applied.
        self.assertTrue(torch.allclose(embedder.W[:,1], torch.ones(d)))
        self.assertTrue(torch.allclose(embedder.V[0,:], torch.ones(d)))


    def test_update_one_sided_rejects_delta_W(self):

        # Set up conditions for test.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Make a NON-one-sided embedder, whose `update` method we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate)

        # Show that we can update covector embeddings for a non-one-sided model
        delta_W = torch.ones(M.shape)
        embedder.update(delta_W=delta_W)

        # Now make a ONE-SIDED embedder, which should reject covector updates.
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate, one_sided=True)
        delta_W = torch.ones(M.shape)
        with self.assertRaises(ValueError):
            embedder.update(delta_W=delta_W)


    def test_integration_with_constrainer(self):

        # Set up test conditions.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # Make an embedder, to test its integration with constrainer.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate,
            constrainer=h.constrainer.glove_constrainer
        )

        # Copy the current embeddings so we can manually calculate the expected
        # updates.
        old_V = embedder.V.clone()
        old_W = embedder.W.clone()

        # Ask the embedder to advance through one update cycle.
        embedder.cycle(print_badness=False)

        # Calculate the expected update, with constraints applied.
        M = torch.tensor(M, dtype=torch.float32)
        M_hat = torch.mm(old_W, old_V)
        delta = M - M_hat
        new_V = old_V + learning_rate * torch.mm(old_W.t(), delta)
        new_W = old_W + learning_rate * torch.mm(delta, old_V.t())

        # Apply the constraints.  Note that the constrainer operates in_place.

        # Verify that manually updated embeddings match those of the embedder.
        h.constrainer.glove_constrainer(new_W, new_V)
        self.assertTrue(torch.allclose(embedder.V, new_V))
        self.assertTrue(torch.allclose(embedder.W, new_W))

        # Verify that the contstraints really were applied.
        self.assertTrue(torch.allclose(embedder.W[:,1], torch.ones(d)))
        self.assertTrue(torch.allclose(embedder.V[0,:], torch.ones(d)))

        # Check that the badness is correct 
        # (badness is based on the error before last update)
        expected_badness = torch.sum(abs(delta)) / (d*d)
        self.assertEqual(expected_badness, embedder.badness)


    def test_mse_embedder(self):
        # Set up conditions for test.
        d = 11
        learning_rate = 0.01
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)
        tolerance = 0.0001

        # Make the embedder, whose convergence we are testing.
        embedder = h.torch_embedder.TorchHilbertEmbedder(
            M, d, h.f_delta.torch_f_mse, learning_rate)

        # Run the embdder for one hundred thousand update cycles.
        embedder.cycle(100000, print_badness=False)

        # Ensure that the embeddings have the right shape.
        self.assertEqual(embedder.V.shape, (M.shape[1],d))
        self.assertEqual(embedder.W.shape, (d,M.shape[0]))

        # Check that we have essentially reached convergence, based on the 
        # fact that the delta value for the embedder is near zero.
        M_hat = torch.mm(embedder.W, embedder.V)
        delta = h.f_delta.torch_f_mse(M, M_hat)
        self.assertTrue(torch.sum(delta) < tolerance)
        





class MockObjective(object):

    def __init__(self, *param_shapes):
        self.param_shapes = param_shapes
        self.updates = []
        self.passed_args = []
        self.params = []
        self.initialize_params()


    def initialize_params(self):
        initial_params = []
        for shape in self.param_shapes:
            np.random.seed(0)
            initial_params.append(np.random.random(shape))
        self.params.append(initial_params)


    def get_gradient(self, offsets=None, pass_args=None):
        self.passed_args.append(pass_args)
        curr_gradient = []
        for i in range(len(self.param_shapes)):
            curr_gradient.append(
                self.params[-1][i] + 0.1 
                + (offsets[i] if offsets is not None else 0)
            )
        return curr_gradient


    def update(self, *updates):
        new_params = []
        for i in range(len(self.param_shapes)):
            new_params.append(self.params[-1][i] + updates[i])
        self.params.append(new_params)

        copied_updates = [a if np.isscalar(a) else a.copy() for a in updates]
        self.updates.append(copied_updates)



class TestSolvers(TestCase):

    def test_momentum_solver(self):
        learning_rate = 0.1
        momentum_decay = 0.8
        times = 3
        mock_objective = MockObjective((1,), (3,3))
        solver = h.solver.MomentumSolver(
            mock_objective, learning_rate, momentum_decay)

        solver.cycle(times=times, pass_args={'a':1})

        # Initialize the parameters using the same random initialization as
        # used by the mock objective.
        expected_params = []
        np.random.seed(0)
        initial_params_0 = np.random.random((1,))
        np.random.seed(0)
        initial_params_1 = np.random.random((3,3))
        expected_params.append((initial_params_0, initial_params_1))

        # Initialize the momentum at zero
        expected_momenta = [(np.zeros((1,)), np.zeros((3,3)))]

        # Compute successive updates
        for i in range(times):
            update_0 = (
                expected_momenta[-1][0] * momentum_decay
                + (expected_params[-1][0] + 0.1) * learning_rate
            )
            update_1 = (
                expected_momenta[-1][1] * momentum_decay
                + (expected_params[-1][1] + 0.1) * learning_rate
            )
            expected_momenta.append((update_0, update_1))

            expected_params.append((
                expected_params[-1][0] + expected_momenta[-1][0],
                expected_params[-1][1] + expected_momenta[-1][1]
            ))

        # Updates should be the successive momenta (excluding the first zero
        # value)
        for expected,found in zip(expected_momenta[1:], mock_objective.updates):
            for e, f in zip(expected, found):
                self.assertTrue(np.allclose(e, f))

        # Test that all the pass_args were received.  Note that the solver
        # will call get_gradient once at the start to determine the shape
        # of the parameters, and None will have been passed as the pass_arg.
        self.assertEqual(
            mock_objective.passed_args, [None, {'a':1}, {'a':1}, {'a':1}])


    def compare_nesterov_momentum_solver_to_optimized(self):

        learning_rate = 0.1
        momentum_decay = 0.8
        times = 3

        mock_objective_1 = MockObjective((1,), (3,3))
        nesterov_solver = h.solver.NesterovSolver(
            mock_objective_1, learning_rate, momentum_decay)

        mock_objective_2 = MockObjective((1,), (3,3))
        nesterov_solver_optimized = h.solver.NesterovSolver(
            mock_objective_2, learning_rate, momentum_decay)

        for i in range(times):

            nesterov_solver.cycle()
            nesterov_solver_optimized.cycle()

            gradient_1 = nesterov_solver.gradient_steps
            gradient_2 = nesterov_solver_optimized.gradient_steps

            for param_1, param_2 in zip(gradient_1, gradient_2):
                self.assertTrue(np.allclose(param_1, param_2))


    def test_nesterov_momentum_solver(self):
        learning_rate = 0.1
        momentum_decay = 0.8
        times = 3
        mo = MockObjective((1,), (3,3))
        solver = h.solver.NesterovSolver(
            mo, learning_rate, momentum_decay)

        solver.cycle(times=times, pass_args={'a':1})

        params_expected = self.calculate_expected_nesterov_params(
            times, learning_rate, momentum_decay
        )

        # Verify that the solver visited to the expected parameter values
        for i in range(len(params_expected)):
            for param, param_expected in zip(mo.params[i], params_expected[i]):
                self.assertTrue(np.allclose(param, param_expected))

        # Test that all the pass_args were received.  Note that the solver
        # will call get_gradient once at the start to determine the shape
        # of the parameters, and None will have been passed as the pass_arg.
        self.assertEqual(
            mo.passed_args, [None, {'a':1}, {'a':1}, {'a':1}])



    def test_nesterov_momentum_solver_optimized(self):
        learning_rate = 0.01
        momentum_decay = 0.8
        times = 3
        mo = MockObjective((1,), (3,3))
        solver = h.solver.NesterovSolverOptimized(
            mo, learning_rate, momentum_decay)

        solver.cycle(times=times, pass_args={'a':1})

        params_expected = self.calculate_expected_nesterov_optimized_params(
            times, learning_rate, momentum_decay
        )

        # Verify that the solver visited to the expected parameter values
        for i in range(len(params_expected)):
            for param, param_expected in zip(mo.params[i], params_expected[i]):
                self.assertTrue(np.allclose(param, param_expected))

        # Test that all the pass_args were received.  Note that the solver
        # will call get_gradient once at the start to determine the shape
        # of the parameters, and None will have been passed as the pass_arg.
        self.assertEqual(
            mo.passed_args, [None, {'a':1}, {'a':1}, {'a':1}])


    def calculate_expected_nesterov_params(
        self, times, learning_rate, momentum_decay
    ):

        # Initialize the parameters using the same random initialization as
        # used by the mock objective.
        params_expected = [[]]
        np.random.seed(0)
        params_expected[0].append(np.random.random((1,)))
        np.random.seed(0)
        params_expected[0].append(np.random.random((3,3)))

        # Solver starts with zero momentum
        momentum_expected = [[np.zeros((1,)), np.zeros((3,3))]]

        # Compute successive updates
        gradient_steps = []
        for i in range(times):

            # In this test, the gradient is always equal to `params + 0.1`
            # Nesterov adds momentum to parameters before taking gradient.
            gradient_steps.append((
                learning_rate * (
                    params_expected[-1][0] + 0.1
                    + momentum_expected[-1][0] * momentum_decay),
                learning_rate * (
                    params_expected[-1][1] + 0.1
                    + momentum_expected[-1][1] * momentum_decay),
            ))

            momentum_expected.append((
                momentum_decay * momentum_expected[-1][0] 
                    + gradient_steps[-1][0],
                momentum_decay * momentum_expected[-1][1]
                    + gradient_steps[-1][1]
            ))

            # Do the accellerated update
            params_expected.append((
                params_expected[-1][0] + momentum_expected[-1][0],
                params_expected[-1][1] + momentum_expected[-1][1],
            ))

        return params_expected
            

    def calculate_expected_nesterov_optimized_params(
        self, times, learning_rate, momentum_decay
    ):

        # Initialize the parameters using the same random initialization as
        # used by the mock objective.
        params_expected = [[]]
        np.random.seed(0)
        params_expected[0].append(np.random.random((1,)))
        np.random.seed(0)
        params_expected[0].append(np.random.random((3,3)))

        # Solver starts with zero momentum
        momentum_expected = [[np.zeros((1,)), np.zeros((3,3))]]

        # Compute successive updates
        gradient_steps = []
        for i in range(times):

            # In this test, the gradient is always equal to `params + 0.1`
            gradient_steps.append((
                (params_expected[-1][0] + 0.1) * learning_rate,
                (params_expected[-1][1] + 0.1) * learning_rate
            ))

            momentum_expected.append((
                momentum_decay * momentum_expected[-1][0] 
                    + gradient_steps[-1][0],
                momentum_decay * momentum_expected[-1][1]
                    + gradient_steps[-1][1]
            ))

            # Do the accellerated update
            params_expected.append((
                params_expected[-1][0] + gradient_steps[-1][0] 
                    + momentum_decay * momentum_expected[-1][0],
                params_expected[-1][1] + gradient_steps[-1][1] 
                    + momentum_decay * momentum_expected[-1][1]
            ))

        return params_expected
            


#TODO: add tests for torch embedder.
class TestEmbedderSolverIntegration(TestCase):

    def test_embedder_solver_integration(self):

        d = 5
        times = 3
        learning_rate = 0.01
        momentum_decay = 0.8
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # This test just makes sure that the solver and embedder interface
        # properly.  All is good as long as this doesn't throw errors.
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)
        solver = h.solver.NesterovSolver(
            embedder, learning_rate, momentum_decay)
        solver.cycle(times=times)


    def test_embedder_nesterov_solver_optimized_integration(self):

        d = 5
        times = 3
        learning_rate = 0.01
        momentum_decay = 0.8
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # This test just makes sure that the solver and embedder interface
        # properly.  All is good as long as this doesn't throw errors.
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)
        solver = h.solver.NesterovSolverOptimized(
            embedder, learning_rate, momentum_decay)
        solver.cycle(times=times)


    def test_embedder_momentum_solver_integration(self):

        d = 5
        times = 3
        learning_rate = 0.01
        momentum_decay = 0.8
        cooc_stats = h.corpus_stats.get_test_stats(2)
        M = h.corpus_stats.calc_positive_PMI(cooc_stats)

        # This test just makes sure that the solver and embedder interface
        # properly.  All is good as long as this doesn't throw errors.
        embedder = h.embedder.HilbertEmbedder(
            M, d, h.f_delta.f_mse, learning_rate)
        solver = h.solver.MomentumSolver(
            embedder, learning_rate, momentum_decay)
        solver.cycle(times=times)


# These functions came from hilbert-experiments, where they were only being
# used to support testing.  Now that the Dictionary and it's testing have moved
# here, I have copied these helper functions and changed them minimally.
def iter_test_fnames():
    for path in os.listdir(h.CONSTANTS.TEST_DOCS_DIR):
        if not skip_file(path):
            yield os.path.basename(path)
def iter_test_paths():
    for fname in iter_test_fnames():
        yield get_test_path(fname)
def get_test_tokens():
    paths = iter_test_paths()
    return read_tokens(paths)
def read_tokens(paths):
    tokens = []
    for path in paths:
        with open(path) as f:
            tokens.extend([token for token in f.read().split()])
    return tokens
def skip_file(fname):
    if fname.startswith('.'):
        return True
    if fname.endswith('.swp') or fname.endswith('.swo'):
        return True
    return False
def get_test_path(fname):
    return os.path.join(h.CONSTANTS.TEST_DOCS_DIR, fname)


class TestDictionary(TestCase):

    def get_test_dictionary(self):

        tokens = get_test_tokens()
        return tokens, h.dictionary.Dictionary(tokens)


    def test_copy(self):

        # NOTE: currently implementation of copy is simply deferred to deepcopy

        tokens, dictionary1 = self.get_test_dictionary()
        dictionary2 = copy(dictionary1)

        # None of the obejects are the same
        self.assertTrue(dictionary2 is not dictionary1)
        self.assertTrue(dictionary2.tokens is not dictionary1.tokens)
        self.assertTrue(dictionary2.token_ids is not dictionary1.token_ids)

        # But they are equal
        self.assertEqual(dictionary2.tokens, dictionary1.tokens)
        self.assertEqual(dictionary2.token_ids, dictionary1.token_ids)


    def test_deepcopy(self):

        # NOTE: currently implementation of copy is simply deferred to deepcopy

        tokens, dictionary1 = self.get_test_dictionary()
        dictionary2 = deepcopy(dictionary1)

        # None of the obejects are the same
        self.assertTrue(dictionary2 is not dictionary1)
        self.assertTrue(dictionary2.tokens is not dictionary1.tokens)
        self.assertTrue(dictionary2.token_ids is not dictionary1.token_ids)

        # But they are equal
        self.assertEqual(dictionary2.tokens, dictionary1.tokens)
        self.assertEqual(dictionary2.token_ids, dictionary1.token_ids)


    def test_dictionary(self):
        tokens, dictionary = self.get_test_dictionary()
        for token in tokens:
            dictionary.add_token(token)

        self.assertEqual(set(tokens), set(dictionary.tokens))
        expected_token_ids = {
            token:idx for idx, token in enumerate(dictionary.tokens)}
        self.assertEqual(expected_token_ids, dictionary.token_ids)


    def test_save_load_dictionary(self):
        write_path = os.path.join(h.CONSTANTS.TEST_DIR, 'test.dictionary')

        # Remove files that could be left from a previous test.
        if os.path.exists(write_path):
            os.remove(write_path)

        tokens, dictionary = self.get_test_dictionary()
        dictionary.save(write_path)
        loaded_dictionary = h.dictionary.Dictionary.load(
            write_path)

        self.assertEqual(loaded_dictionary.tokens, dictionary.tokens)
        self.assertEqual(loaded_dictionary.token_ids, dictionary.token_ids)

        # Cleanup
        os.remove(write_path)



class TestCoocStats(TestCase):


    def get_test_cooccurrence_stats(self):
        DICTIONARY = h.dictionary.Dictionary([
            'banana', 'socks', 'car', 'field'])
        COUNTS = {
            (0,1):3, (1,0):3,
            (0,3):1, (3,0):1,
            (2,1):1, (1,2):1,
            (0,2):1, (2,0):1
        }
        DIJ = ([3,1,1,1,3,1,1,1], ([0,0,2,0,1,3,1,2], [1,3,1,2,0,0,2,0]))
        ARRAY = np.array([[0,3,1,1],[3,0,1,0],[1,1,0,0],[1,0,0,0]])
        return DICTIONARY, COUNTS, DIJ, ARRAY


    def test_invalid_arguments(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()

        # Can make an empty CoocStats instance.
        h.cooc_stats.CoocStats()

        # Can make a non-empty CoocStats instance using counts and
        # a matching dictionary.
        h.cooc_stats.CoocStats(dictionary, counts)

        # Must supply a dictionary to make a  non-empty CoocStats
        # instance when using counts.
        with self.assertRaises(ValueError):
            h.cooc_stats.CoocStats(
                counts=counts)

        # Can make a non-empty CoocStats instance using Nxx and
        # a matching dictionary.
        Nxx = sparse.coo_matrix(dij).tocsr()
        h.cooc_stats.CoocStats(dictionary, counts)

        # Must supply a dictionary to make a  non-empty CoocStats
        # instance when using Nxx.
        with self.assertRaises(ValueError):
            h.cooc_stats.CoocStats(Nxx=Nxx)

        # Cannot provide both an Nxx and counts
        with self.assertRaises(ValueError):
            h.cooc_stats.CoocStats(
                dictionary, counts, Nxx=Nxx)


    def test_add_when_basis_is_counts(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        cooccurrence = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)
        cooccurrence.add('banana', 'rice')
        self.assertEqual(cooccurrence.dictionary.get_id('rice'), 4)
        expected_counts = Counter(counts)
        expected_counts[0,4] += 1
        self.assertEqual(cooccurrence.counts, expected_counts)


    def test_add_when_basis_is_Nxx(self):

        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        Nxx = array

        Nx = np.sum(Nxx, axis=1).reshape(-1,1)

        # Create a cooccurrence instance using counts
        cooccurrence = h.cooc_stats.CoocStats(
            dictionary, Nxx=Nxx, verbose=False)

        # Currently the cooccurrence instance has no internal counter for
        # cooccurrences, because it is based on the cooccurrence_array
        self.assertTrue(cooccurrence._counts is None)
        self.assertTrue(np.allclose(cooccurrence._Nxx.toarray(), Nxx))
        self.assertTrue(np.allclose(cooccurrence._Nx, Nx))
        self.assertTrue(np.allclose(cooccurrence.Nxx.toarray(), Nxx))
        self.assertTrue(np.allclose(cooccurrence.Nx, Nx))

        # Adding more cooccurrence statistics will force it to "decompile" into
        # a counter, then add to the counter.  This will cause the stale Nxx
        # arrays to be dropped.
        cooccurrence.add('banana', 'rice')
        cooccurrence.add('rice', 'banana')
        expected_counts = Counter(counts)
        expected_counts[4,0] += 1
        expected_counts[0,4] += 1
        self.assertEqual(cooccurrence._counts, expected_counts)
        self.assertEqual(cooccurrence._Nxx, None)
        self.assertEqual(cooccurrence._Nx, None)

        # Asking for Nxx forces it to sync itself.  
        # Ensure it it obtains the correct cooccurrence matrix
        expected_Nxx = np.append(array, [[1],[0],[0],[0]], axis=1)
        expected_Nxx = np.append(expected_Nxx, [[1,0,0,0,0]], axis=0)
        expected_Nx = np.sum(expected_Nxx, axis=1).reshape(-1,1)
        self.assertTrue(np.allclose(cooccurrence.Nxx.toarray(), expected_Nxx))
        self.assertTrue(np.allclose(cooccurrence.Nx, expected_Nx))


    def test_uncompile(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        Nxx = sparse.coo_matrix(dij)
        Nx = np.array(np.sum(Nxx, axis=1)).reshape(-1)

        # Create a cooccurrence instance using Nxx
        cooccurrence = h.cooc_stats.CoocStats(
            dictionary, Nxx=Nxx, verbose=False)
        self.assertEqual(cooccurrence._counts, None)

        cooccurrence.decompile()
        self.assertEqual(cooccurrence._counts, counts)



    def test_compile(self):

        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()

        # Create a cooccurrence instance using counts
        cooccurrence = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)

        # The cooccurrence instance has no Nxx array, but it will be calculated
        # when we try to access it directly.
        self.assertEqual(cooccurrence._Nxx, None)
        self.assertEqual(cooccurrence._Nx, None)
        self.assertTrue(np.allclose(cooccurrence.Nxx.toarray(), array))
        self.assertTrue(np.allclose(
            cooccurrence.Nx, np.sum(array, axis=1).reshape(-1,1)))

        # We can still add more counts.  This causes it to drop the stale Nxx.
        cooccurrence.add('banana', 'rice')
        cooccurrence.add('rice', 'banana')
        self.assertEqual(cooccurrence._Nxx, None)
        self.assertEqual(cooccurrence._Nx, None)

        # Asking for an array forces it to sync itself.  This time start with
        # denseNxx.
        expected_Nxx = np.append(array, [[1],[0],[0],[0]], axis=1)
        expected_Nxx = np.append(expected_Nxx, [[1,0,0,0,0]], axis=0)
        self.assertTrue(np.allclose(cooccurrence.Nxx.toarray(), expected_Nxx))
        self.assertTrue(np.allclose(
            cooccurrence.Nx, np.sum(expected_Nxx, axis=1).reshape(-1,1)))

        # Adding more counts once again causes it to drop the stale Nxx.
        cooccurrence.add('banana', 'field')
        cooccurrence.add('field', 'banana')
        self.assertEqual(cooccurrence._Nxx, None)
        self.assertEqual(cooccurrence._Nx, None)

        # Asking for an array forces it to sync itself.  This time start with
        # Nx.
        expected_Nxx[0,3] += 1
        expected_Nxx[3,0] += 1
        self.assertTrue(np.allclose(cooccurrence.Nxx.toarray(), expected_Nxx))
        self.assertTrue(np.allclose(
            cooccurrence.Nx, np.sum(expected_Nxx, axis=1).reshape(-1,1)))



    def test_sort(self):
        unsorted_dictionary = h.dictionary.Dictionary([
            'field', 'car', 'socks', 'banana'
        ])
        unsorted_counts = {
            (0,3): 1, (3,0): 1,
            (1,2): 1, (2,1): 1,
            (1,3): 1, (3,1): 1,
            (2,3): 3, (3,2): 3
        }
        unsorted_Nxx = np.array([
            [0,0,0,1],
            [0,0,1,1],
            [0,1,0,3],
            [1,1,3,0],
        ])
        sorted_dictionary = h.dictionary.Dictionary([
            'banana', 'socks', 'car', 'field'])
        sorted_counts = {
            (0,1):3, (1,0):3,
            (0,3):1, (3,0):1,
            (2,1):1, (1,2):1,
            (0,2):1, (2,0):1
        }
        sorted_array = np.array([
            [0,3,1,1],
            [3,0,1,0],
            [1,1,0,0],
            [1,0,0,0]
        ])
        cooccurrence = h.cooc_stats.CoocStats(
            unsorted_dictionary, unsorted_counts, verbose=False
        )
        self.assertTrue(np.allclose(cooccurrence.Nxx.toarray(), sorted_array))
        self.assertEqual(cooccurrence.counts, sorted_counts)
        self.assertEqual(
            cooccurrence.dictionary.tokens, sorted_dictionary.tokens)


    def test_save_load(self):

        write_path = os.path.join(
            h.CONSTANTS.TEST_DIR, 'test-save-load-cooccurrences')
        if os.path.exists(write_path):
            shutil.rmtree(write_path)

        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()

        # Create a cooccurrence instance using counts
        cooccurrence = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)

        # Save it, then load it
        cooccurrence.save(write_path)
        cooccurrence2 = h.cooc_stats.CoocStats.load(
            write_path, verbose=False)

        self.assertEqual(
            cooccurrence2.dictionary.tokens, 
            cooccurrence.dictionary.tokens
        )
        self.assertEqual(cooccurrence2.counts, cooccurrence.counts)
        self.assertTrue(np.allclose(
            cooccurrence2.Nxx.toarray(), cooccurrence.Nxx.toarray()))
        self.assertTrue(np.allclose(cooccurrence2.Nx, cooccurrence.Nx))

        shutil.rmtree(write_path)


    def test_density(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        cooccurrence = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)
        self.assertEqual(cooccurrence.density(), 0.5)
        self.assertEqual(cooccurrence.density(2), 0.125)


    def test_truncate(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        cooccurrence = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)
        cooccurrence.truncate(3)
        truncated_array = np.array([
            [0,3,1],
            [3,0,1],
            [1,1,0],
        ])

        self.assertTrue(
            np.allclose(cooccurrence.Nxx.toarray(), truncated_array))


    def test_dict_to_sparse(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        csr_matrix = h.cooc_stats.dict_to_sparse(counts)
        self.assertTrue(isinstance(csr_matrix, sparse.csr_matrix))
        self.assertTrue(np.allclose(csr_matrix.todense(), array))


    def test_deepcopy(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        cooccurrence1 = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)

        cooccurrence2 = deepcopy(cooccurrence1)

        self.assertTrue(cooccurrence2 is not cooccurrence1)
        self.assertTrue(
            cooccurrence2.dictionary is not cooccurrence1.dictionary)
        self.assertTrue(cooccurrence2.counts is not cooccurrence1.counts)
        self.assertTrue(cooccurrence2.Nxx is not cooccurrence1.Nxx)
        self.assertTrue(cooccurrence2.Nx is not cooccurrence1.Nx)

        self.assertTrue(np.allclose(
            cooccurrence2.Nxx.toarray(), cooccurrence1.Nxx.toarray()))
        self.assertTrue(np.allclose(cooccurrence2.Nx, cooccurrence1.Nx))
        self.assertEqual(cooccurrence2.N, cooccurrence1.N)
        self.assertEqual(cooccurrence2.counts, cooccurrence1.counts)
        self.assertEqual(cooccurrence2.verbose, cooccurrence1.verbose)
        self.assertEqual(cooccurrence2.verbose, cooccurrence1.verbose)


    def test_copy(self):
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        cooccurrence1 = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)

        cooccurrence2 = copy(cooccurrence1)

        self.assertTrue(cooccurrence2 is not cooccurrence1)
        self.assertTrue(
            cooccurrence2.dictionary is not cooccurrence1.dictionary)
        self.assertTrue(cooccurrence2.counts is not cooccurrence1.counts)
        self.assertTrue(cooccurrence2.Nxx is not cooccurrence1.Nxx)
        self.assertTrue(cooccurrence2.Nx is not cooccurrence1.Nx)

        self.assertTrue(np.allclose(
            cooccurrence2.Nxx.toarray(), cooccurrence1.Nxx.toarray()))
        self.assertTrue(np.allclose(cooccurrence2.Nx, cooccurrence1.Nx))
        self.assertEqual(cooccurrence2.N, cooccurrence1.N)
        self.assertEqual(cooccurrence2.counts, cooccurrence1.counts)
        self.assertEqual(cooccurrence2.verbose, cooccurrence1.verbose)
        self.assertEqual(cooccurrence2.verbose, cooccurrence1.verbose)


    def test_add(self):
        """
        When CoocStats add, their counts add.
        """

        # Make one CoocStat instance to be added.
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        cooccurrence1 = h.cooc_stats.CoocStats(
            dictionary, counts, verbose=False)

        # Make another CoocStat instance to be added.
        token_pairs2 = [
            ('banana', 'banana'),
            ('banana','car'), ('banana','car'),
            ('banana','socks'), ('cave','car'), ('cave','socks')
        ]
        dictionary2 = h.dictionary.Dictionary([
            'banana', 'car', 'socks', 'cave'])
        counts2 = {
            (0,0):2,
            (0,1):2, (0,2):1, (3,1):1, (3,2):1,
            (1,0):2, (2,0):1, (1,3):1, (2,3):1
        }
        array2 = np.array([
            [2,2,1,0],
            [2,0,0,1],
            [1,0,0,1],
            [0,1,1,0],
        ])

        cooccurrence2 = h.cooc_stats.CoocStats(verbose=False)
        for tok1, tok2 in token_pairs2:
            cooccurrence2.add(tok1, tok2)
            cooccurrence2.add(tok2, tok1)

        cooccurrence_sum = cooccurrence2 + cooccurrence1

        # Ensure that cooccurrence1 was not changed
        dictionary, counts, dij, array = self.get_test_cooccurrence_stats()
        self.assertEqual(cooccurrence1.counts, counts)
        self.assertTrue(np.allclose(cooccurrence1.Nxx.toarray(), array))
        expected_Nx = np.sum(array, axis=1).reshape(-1,1)
        self.assertTrue(np.allclose(cooccurrence1.Nx, expected_Nx))
        self.assertEqual(cooccurrence1.N, np.sum(array))
        self.assertEqual(cooccurrence1.dictionary.tokens, dictionary.tokens)
        self.assertEqual(
            cooccurrence1.dictionary.token_ids, dictionary.token_ids)
        self.assertEqual(cooccurrence1.verbose, False)

        # Ensure that cooccurrence2 was not changed
        self.assertEqual(cooccurrence2.counts, counts2)

        self.assertTrue(np.allclose(cooccurrence2.Nxx.toarray(), array2))
        expected_Nx2 = np.sum(array2, axis=1).reshape(-1,1)
        self.assertTrue(np.allclose(cooccurrence2.Nx, expected_Nx2))
        self.assertEqual(cooccurrence2.N, np.sum(array2))
        self.assertEqual(cooccurrence2.dictionary.tokens, dictionary2.tokens)
        self.assertEqual(
            cooccurrence2.dictionary.token_ids, dictionary2.token_ids)
        self.assertEqual(cooccurrence2.verbose, False)
        

        # Ensure that cooccurrence_sum is as desired
        dictionary_sum = h.dictionary.Dictionary([
            'banana', 'socks', 'car', 'cave', 'field'])
        array_sum = np.array([
            [2, 4, 3, 0, 1],
            [4, 0, 1, 1, 0],
            [3, 1, 0, 1, 0],
            [0, 1, 1, 0, 0],
            [1, 0, 0, 0, 0],
        ])
        Nx_sum = np.sum(array_sum, axis=1).reshape(-1,1)
        counts_sum = Counter({
            (0, 0): 2, 
            (0, 1): 4, (1, 0): 4, (2, 0): 3, (0, 2): 3, (1, 2): 1, (3, 2): 1,
            (3, 1): 1, (2, 1): 1, (1, 3): 1, (2, 3): 1, (0, 4): 1, (4, 0): 1
        })
        #self.assertEqual(
        #    cooccurrence_sum.dictionary.tokens, dictionary_sum.tokens)
        #self.assertEqual(
        #    cooccurrence_sum.dictionary.token_ids, dictionary_sum.token_ids)
        self.assertTrue(np.allclose(cooccurrence_sum.Nxx.toarray(), array_sum))
        self.assertTrue(np.allclose(cooccurrence_sum.Nx, Nx_sum))
        self.assertTrue(cooccurrence_sum.N, cooccurrence1.N + cooccurrence2.N)
        self.assertEqual(cooccurrence_sum.counts, counts_sum)


if __name__ == '__main__':
    main()

