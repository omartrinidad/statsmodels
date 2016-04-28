"""
Tests for simulation smoothing

Author: Chad Fulton
License: Simplified-BSD
"""
from __future__ import division, absolute_import#, print_function

import numpy as np
import pandas as pd
import os

from statsmodels import datasets
from statsmodels.tsa.statespace import mlemodel, sarimax
from statsmodels.tsa.statespace.tools import compatibility_mode
from statsmodels.tsa.statespace.kalman_filter import (
    FILTER_CONVENTIONAL, FILTER_COLLAPSED, FILTER_UNIVARIATE)
from statsmodels.tsa.statespace.kalman_smoother import (
    SMOOTH_CONVENTIONAL, SMOOTH_CLASSICAL, SMOOTH_ALTERNATIVE,
    SMOOTH_UNIVARIATE)
from numpy.testing import assert_allclose, assert_almost_equal, assert_equal, assert_raises
from nose.exc import SkipTest

current_path = os.path.dirname(os.path.abspath(__file__))


class MultivariateVARKnown(object):
    """
    Tests for simulation smoothing values in a couple of special cases of
    variates. Both computed values and KFAS values are used for comparison
    against the simulation smoother output.
    """
    @classmethod
    def setup_class(cls, missing=None, test_against_KFAS=True, *args, **kwargs):
        cls.test_against_KFAS = test_against_KFAS
        # Data
        dta = datasets.macrodata.load_pandas().data
        dta.index = pd.date_range(start='1959-01-01', end='2009-7-01',
                                  freq='QS')
        obs = np.log(dta[['realgdp', 'realcons', 'realinv']]).diff().ix[1:]

        if missing == 'all':
            obs.ix[0:50, :] = np.nan
        elif missing == 'partial':
            obs.ix[0:50, 0] = np.nan
        elif missing == 'mixed':
            obs.ix[0:50, 0] = np.nan
            obs.ix[19:70, 1] = np.nan
            obs.ix[39:90, 2] = np.nan
            obs.ix[119:130, 0] = np.nan
            obs.ix[119:130, 2] = np.nan
            obs.iloc[-10:, :] = np.nan

        if test_against_KFAS:
            obs = obs.iloc[:9]

        # Create the model
        mod = mlemodel.MLEModel(obs, k_states=3, k_posdef=3, **kwargs)
        mod['design'] = np.eye(3)
        mod['obs_cov'] = np.array([[ 0.0000640649,  0.          ,  0.          ],
                                   [ 0.          ,  0.0000572802,  0.          ],
                                   [ 0.          ,  0.          ,  0.0017088585]])
        mod['transition'] = np.array([[-0.1119908792,  0.8441841604,  0.0238725303],
                                      [ 0.2629347724,  0.4996718412, -0.0173023305],
                                      [-3.2192369082,  4.1536028244,  0.4514379215]])
        mod['selection'] = np.eye(3)
        mod['state_cov'] = np.array([[ 0.0000640649,  0.0000388496,  0.0002148769],
                                     [ 0.0000388496,  0.0000572802,  0.000001555 ],
                                     [ 0.0002148769,  0.000001555 ,  0.0017088585]])
        mod.initialize_approximate_diffuse(1e6)
        mod.ssm.filter_univariate = True
        cls.model = mod
        cls.results = mod.smooth([], return_ssm=True)

        if not compatibility_mode:
            cls.sim = cls.model.simulation_smoother()

    def test_loglike(self):
        assert_allclose(np.sum(self.results.llf_obs), self.true_llf)

    def test_simulate_0(self):
        n = 10

        # Test with all inputs as zeros
        measurement_shocks = np.zeros((n, self.model.k_endog))
        state_shocks = np.zeros((n, self.model.ssm.k_posdef))
        initial_state = np.zeros(self.model.k_endog)
        obs, states = self.model.ssm.simulate(
            nsimulations=n, measurement_shocks=measurement_shocks,
            state_shocks=state_shocks, initial_state=initial_state)

        assert_allclose(obs, np.zeros((n, self.model.k_endog)))
        assert_allclose(states, np.zeros((n, self.model.k_states)))

    def test_simulate_1(self):
        n = 10

        # Test with np.arange / 10 measurement shocks only
        measurement_shocks = np.reshape(
            np.arange(n * self.model.k_endog) / 10.,
            (n, self.model.k_endog))
        state_shocks = np.zeros((n, self.model.ssm.k_posdef))
        initial_state = np.zeros(self.model.k_endog)
        obs, states = self.model.ssm.simulate(
            nsimulations=n, measurement_shocks=measurement_shocks,
            state_shocks=state_shocks, initial_state=initial_state)

        assert_allclose(obs, np.reshape(
            np.arange(n * self.model.k_endog) / 10.,
            (n, self.model.k_endog)))
        assert_allclose(states, np.zeros((n, self.model.k_states)))

    def test_simulate_2(self):
        n = 10
        T = self.model['transition']

        # Test with non-zero state shocks and initial state
        measurement_shocks = np.zeros((n, self.model.k_endog))
        state_shocks = np.ones((n, self.model.ssm.k_posdef))
        initial_state = np.ones(self.model.k_endog) * 2.5
        obs, states = self.model.ssm.simulate(
            nsimulations=n, measurement_shocks=measurement_shocks,
            state_shocks=state_shocks, initial_state=initial_state)

        desired = np.zeros((n, self.model.k_endog))
        desired[0] = initial_state
        for i in range(1, n):
            desired[i] = np.dot(T, desired[i-1]) + state_shocks[i]

        assert_allclose(obs, desired)
        assert_allclose(states, desired)

    def test_simulation_smoothing_0(self):
        # Simulation smoothing when setting all variates to zeros
        # In this case:
        # - unconditional disturbances are zero, because they are simply
        #   transformed to have the appropriate variance matrix, but keep the
        #   same mean - of zero
        # - generated states are zeros, because initial state is
        #   zeros and all state disturbances are zeros
        # - generated observations are zeros, because states are zeros and all
        #    measurement disturbances are zeros
        # - The simulated state is equal to the smoothed state from the
        #   original model, because
        #   simulated state = (generated state - smoothed generated state +
        #                      smoothed state)
        #   and here generated state = smoothed generated state = 0
        # - The simulated measurement disturbance is equal to the smoothed
        #   measurement disturbance for very similar reasons, because
        #   simulated measurement disturbance = (
        #       generated measurement disturbance -
        #       smoothed generated measurement disturbance +
        #       smoothed measurement disturbance)
        #   and here generated measurement disturbance and
        #   smoothed generated measurement disturbance are zero.
        # - The simulated state disturbance is equal to the smoothed
        #   state disturbance for exactly the same reason as above.
        if compatibility_mode:
            raise SkipTest
        sim = self.sim
        Z = self.model['design']

        n_disturbance_variates = (
            (self.model.k_endog + self.model.ssm.k_posdef) * self.model.nobs)

        # Test against known quantities (see above for description)
        sim.simulate(disturbance_variates=np.zeros(n_disturbance_variates),
                     initial_state_variates=np.zeros(self.model.k_states))
        assert_allclose(sim.generated_measurement_disturbance, 0)
        assert_allclose(sim.generated_state_disturbance, 0)
        assert_allclose(sim.generated_state, 0)
        assert_allclose(sim.generated_obs, 0)
        assert_allclose(sim.simulated_state, self.results.smoothed_state)
        assert_allclose(sim.simulated_measurement_disturbance,
                        self.results.smoothed_measurement_disturbance)
        assert_allclose(sim.simulated_state_disturbance,
                        self.results.smoothed_state_disturbance)

        # Test against R package KFAS values
        if self.test_against_KFAS:
            path = (current_path + os.sep +
                    'results/results_simulation_smoothing0.csv')
            true = pd.read_csv(path)

            assert_allclose(sim.simulated_state,
                            true[['state1', 'state2', 'state3']].T,
                            atol=1e-7)
            assert_allclose(sim.simulated_measurement_disturbance,
                            true[['eps1', 'eps2', 'eps3']].T,
                            atol=1e-7)
            assert_allclose(sim.simulated_state_disturbance,
                            true[['eta1', 'eta2', 'eta3']].T,
                            atol=1e-7)
            signals = np.zeros((3, self.model.nobs))
            for t in range(self.model.nobs):
                signals[:, t] = np.dot(Z, sim.simulated_state[:, t])
            assert_allclose(signals, true[['signal1', 'signal2', 'signal3']].T,
                            atol=1e-7)

    def test_simulation_smoothing_1(self):
        # Test with measurement disturbance as np.arange / 10., all other
        # disturbances are zeros
        if compatibility_mode:
            raise SkipTest
        sim = self.sim

        Z = self.model['design']

        # Construct the variates
        measurement_disturbance_variates = np.reshape(
            np.arange(self.model.nobs * self.model.k_endog) / 10.,
            (self.model.nobs, self.model.k_endog))
        disturbance_variates = np.r_[
            measurement_disturbance_variates.ravel(),
            np.zeros(self.model.nobs * self.model.ssm.k_posdef)]

        # Compute some additional known quantities
        generated_measurement_disturbance = np.zeros(
            measurement_disturbance_variates.shape)
        chol = np.linalg.cholesky(self.model['obs_cov'])
        for t in range(self.model.nobs):
            generated_measurement_disturbance[t] = np.dot(
                chol, measurement_disturbance_variates[t])

        generated_model = mlemodel.MLEModel(
            generated_measurement_disturbance, k_states=3, k_posdef=3)
        for name in ['design', 'obs_cov', 'transition', 'selection', 'state_cov']:
            generated_model[name] = self.model[name]
        generated_model.initialize_approximate_diffuse(1e6)
        generated_model.ssm.filter_univariate = True
        generated_res = generated_model.ssm.smooth()
        simulated_state = (
            0 - generated_res.smoothed_state + self.results.smoothed_state)
        simulated_measurement_disturbance = (
            generated_measurement_disturbance.T -
            generated_res.smoothed_measurement_disturbance +
            self.results.smoothed_measurement_disturbance)
        simulated_state_disturbance = (
            0 - generated_res.smoothed_state_disturbance +
            self.results.smoothed_state_disturbance)

        # Test against known values
        sim.simulate(disturbance_variates=disturbance_variates,
                     initial_state_variates=np.zeros(self.model.k_states))
        assert_allclose(sim.generated_measurement_disturbance,
                        generated_measurement_disturbance)
        assert_allclose(sim.generated_state_disturbance, 0)
        assert_allclose(sim.generated_state, 0)
        assert_allclose(sim.generated_obs,
                        generated_measurement_disturbance.T)
        assert_allclose(sim.simulated_state, simulated_state)
        assert_allclose(sim.simulated_measurement_disturbance,
                        simulated_measurement_disturbance)
        assert_allclose(sim.simulated_state_disturbance,
                        simulated_state_disturbance)

        # Test against R package KFAS values
        if self.test_against_KFAS:
            path = (current_path + os.sep +
                    'results/results_simulation_smoothing1.csv')
            true = pd.read_csv(path)
            assert_allclose(sim.simulated_state,
                            true[['state1', 'state2', 'state3']].T,
                            atol=1e-7)
            assert_allclose(sim.simulated_measurement_disturbance,
                            true[['eps1', 'eps2', 'eps3']].T,
                            atol=1e-7)
            assert_allclose(sim.simulated_state_disturbance,
                            true[['eta1', 'eta2', 'eta3']].T,
                            atol=1e-7)
            signals = np.zeros((3, self.model.nobs))
            for t in range(self.model.nobs):
                signals[:, t] = np.dot(Z, sim.simulated_state[:, t])
            assert_allclose(signals, true[['signal1', 'signal2', 'signal3']].T,
                            atol=1e-7)

    def test_simulation_smoothing_2(self):
        # Test with measurement and state disturbances as np.arange / 10.,
        # initial state variates are zeros.
        if compatibility_mode:
            raise SkipTest
        sim = self.sim

        Z = self.model['design']
        T = self.model['transition']

        # Construct the variates
        measurement_disturbance_variates = np.reshape(
            np.arange(self.model.nobs * self.model.k_endog) / 10.,
            (self.model.nobs, self.model.k_endog))
        state_disturbance_variates = np.reshape(
            np.arange(self.model.nobs * self.model.ssm.k_posdef) / 10.,
            (self.model.nobs, self.model.ssm.k_posdef))
        disturbance_variates = np.r_[
            measurement_disturbance_variates.ravel(),
            state_disturbance_variates.ravel()]
        initial_state_variates = np.zeros(3)

        # Compute some additional known quantities
        generated_measurement_disturbance = np.zeros(
            measurement_disturbance_variates.shape)
        chol = np.linalg.cholesky(self.model['obs_cov'])
        for t in range(self.model.nobs):
            generated_measurement_disturbance[t] = np.dot(
                chol, measurement_disturbance_variates[t])

        generated_state_disturbance = np.zeros(
            state_disturbance_variates.shape)
        chol = np.linalg.cholesky(self.model['state_cov'])
        for t in range(self.model.nobs):
            generated_state_disturbance[t] = np.dot(
                chol, state_disturbance_variates[t])

        generated_obs = np.zeros((self.model.k_endog, self.model.nobs))
        generated_state = np.zeros((self.model.k_states, self.model.nobs+1))
        chol = np.linalg.cholesky(self.results.initial_state_cov)
        generated_state[:, 0] = (
            self.results.initial_state + np.dot(chol, initial_state_variates))
        for t in range(self.model.nobs):
            generated_state[:, t+1] = (np.dot(T, generated_state[:, t]) +
                                       generated_state_disturbance.T[:, t])
            generated_obs[:, t] = (np.dot(Z, generated_state[:, t]) +
                                   generated_measurement_disturbance.T[:, t])

        generated_model = mlemodel.MLEModel(
            generated_obs.T, k_states=3, k_posdef=3)
        for name in ['design', 'obs_cov', 'transition', 'selection', 'state_cov']:
            generated_model[name] = self.model[name]
        generated_model.initialize_approximate_diffuse(1e6)
        generated_model.ssm.filter_univariate = True
        generated_res = generated_model.ssm.smooth()
        simulated_state = (
            generated_state[:, :-1] - generated_res.smoothed_state +
            self.results.smoothed_state)
        simulated_measurement_disturbance = (
            generated_measurement_disturbance.T -
            generated_res.smoothed_measurement_disturbance +
            self.results.smoothed_measurement_disturbance)
        simulated_state_disturbance = (
            generated_state_disturbance.T -
            generated_res.smoothed_state_disturbance +
            self.results.smoothed_state_disturbance)

        # Test against known values
        sim.simulate(disturbance_variates=disturbance_variates,
                     initial_state_variates=np.zeros(self.model.k_states))

        assert_allclose(sim.generated_measurement_disturbance,
                        generated_measurement_disturbance)
        assert_allclose(sim.generated_state_disturbance,
                        generated_state_disturbance)
        assert_allclose(sim.generated_state, generated_state)
        assert_allclose(sim.generated_obs, generated_obs)
        assert_allclose(sim.simulated_state, simulated_state)
        assert_allclose(sim.simulated_measurement_disturbance.T,
                        simulated_measurement_disturbance.T)
        assert_allclose(sim.simulated_state_disturbance,
                        simulated_state_disturbance)

        # Test against R package KFAS values
        if self.test_against_KFAS:
            path = (current_path + os.sep +
                    'results/results_simulation_smoothing2.csv')
            true = pd.read_csv(path)
            assert_allclose(sim.simulated_state.T,
                            true[['state1', 'state2', 'state3']],
                            atol=1e-7)
            assert_allclose(sim.simulated_measurement_disturbance,
                            true[['eps1', 'eps2', 'eps3']].T,
                            atol=1e-7)
            assert_allclose(sim.simulated_state_disturbance,
                            true[['eta1', 'eta2', 'eta3']].T,
                            atol=1e-7)
            signals = np.zeros((3, self.model.nobs))
            for t in range(self.model.nobs):
                signals[:, t] = np.dot(Z, sim.simulated_state[:, t])
            assert_allclose(signals, true[['signal1', 'signal2', 'signal3']].T,
                            atol=1e-7)


class TestMultivariateVARKnown(MultivariateVARKnown):
    @classmethod
    def setup_class(cls, *args, **kwargs):
        super(TestMultivariateVARKnown, cls).setup_class()
        cls.true_llf = 39.01246166


class TestMultivariateVARKnownMissingAll(MultivariateVARKnown):
    """
    Notes
    -----
    Can't test against KFAS because they have a different behavior for
    missing entries. When an entry is missing, KFAS does not draw a simulation
    smoothed value for that entry, whereas we draw from the unconditional
    distribution. It appears there is nothing to definitively recommend one
    approach over the other, but it makes it difficult to line up the variates
    correctly in order to replicate results.
    """
    @classmethod
    def setup_class(cls, *args, **kwargs):
        super(TestMultivariateVARKnownMissingAll, cls).setup_class(
            missing='all', test_against_KFAS=False)
        cls.true_llf = 1305.739288


class TestMultivariateVARKnownMissingPartial(MultivariateVARKnown):
    @classmethod
    def setup_class(cls, *args, **kwargs):
        super(TestMultivariateVARKnownMissingPartial, cls).setup_class(
            missing='partial', test_against_KFAS=False)
        cls.true_llf = 1518.449598


class TestMultivariateVARKnownMissingMixed(MultivariateVARKnown):
    @classmethod
    def setup_class(cls, *args, **kwargs):
        super(TestMultivariateVARKnownMissingMixed, cls).setup_class(
            missing='mixed', test_against_KFAS=False)
        cls.true_llf = 1117.265303


class MultivariateVAR(object):
    """
    Tests for simulation smoothing
    """
    @classmethod
    def setup_class(cls, missing='none', *args, **kwargs):
        # Data
        dta = datasets.macrodata.load_pandas().data
        dta.index = pd.date_range(start='1959-01-01', end='2009-7-01',
                                  freq='QS')
        obs = np.log(dta[['realgdp', 'realcons', 'realinv']]).diff().ix[1:]

        if missing == 'all':
            obs.ix[0:50, :] = np.nan
        elif missing == 'partial':
            obs.ix[0:50, 0] = np.nan
        elif missing == 'mixed':
            obs.ix[0:50, 0] = np.nan
            obs.ix[19:70, 1] = np.nan
            obs.ix[39:90, 2] = np.nan
            obs.ix[119:130, 0] = np.nan
            obs.ix[119:130, 2] = np.nan
            obs.iloc[-10:, :] = np.nan

        # Create the model
        mod = mlemodel.MLEModel(obs, k_states=3, k_posdef=3, **kwargs)
        mod['design'] = np.eye(3)
        mod['obs_cov'] = np.array([[ 0.0000640649,  0.          ,  0.          ],
                                   [ 0.          ,  0.0000572802,  0.          ],
                                   [ 0.          ,  0.          ,  0.0017088585]])
        mod['transition'] = np.array([[-0.1119908792,  0.8441841604,  0.0238725303],
                                      [ 0.2629347724,  0.4996718412, -0.0173023305],
                                      [-3.2192369082,  4.1536028244,  0.4514379215]])
        mod['selection'] = np.eye(3)
        mod['state_cov'] = np.array([[ 0.0000640649,  0.0000388496,  0.0002148769],
                                     [ 0.0000388496,  0.0000572802,  0.000001555 ],
                                     [ 0.0002148769,  0.000001555 ,  0.0017088585]])
        mod.initialize_approximate_diffuse(1e6)
        mod.ssm.filter_univariate = True
        cls.model = mod
        cls.results = mod.smooth([], return_ssm=True)

        if not compatibility_mode:
            cls.sim = cls.model.simulation_smoother()

    def test_loglike(self):
        assert_allclose(np.sum(self.results.llf_obs), self.true_llf)

    def test_simulation_smoothing(self):
        if compatibility_mode:
            raise SkipTest
        sim = self.sim

        Z = self.model['design']

        # Simulate with known variates
        sim.simulate(disturbance_variates=self.variates[:-3],
                     initial_state_variates=self.variates[-3:])

        # Test against R package KFAS values
        assert_allclose(sim.simulated_state.T,
                        self.true[['state1', 'state2', 'state3']],
                        atol=1e-7)
        assert_allclose(sim.simulated_measurement_disturbance,
                        self.true[['eps1', 'eps2', 'eps3']].T,
                        atol=1e-7)
        assert_allclose(sim.simulated_state_disturbance,
                        self.true[['eta1', 'eta2', 'eta3']].T,
                        atol=1e-7)
        signals = np.zeros((3, self.model.nobs))
        for t in range(self.model.nobs):
            signals[:, t] = np.dot(Z, sim.simulated_state[:, t])
        assert_allclose(signals,
                        self.true[['signal1', 'signal2', 'signal3']].T,
                        atol=1e-7)


class TestMultivariateVAR(MultivariateVAR):
    @classmethod
    def setup_class(cls):
        super(TestMultivariateVAR, cls).setup_class()
        path = (current_path + os.sep +
                'results/results_simulation_smoothing3_variates.csv')
        cls.variates = pd.read_csv(path).values.squeeze()
        path = (current_path + os.sep +
                'results/results_simulation_smoothing3.csv')
        cls.true = pd.read_csv(path)
        cls.true_llf = 1695.34872
