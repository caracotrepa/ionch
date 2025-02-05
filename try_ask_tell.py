# imports
import matplotlib.pyplot as plt

from setup import *
import pints
import pickle as pkl
plt.ioff()

# definitions
def ion_channel_model(t, x, theta):
    a, r = x[:2]
    *p, g = theta[:9]
    v = V(t)
    k1 = p[0] * np.exp(p[1] * v)
    k2 = p[2] * np.exp(-p[3] * v)
    k3 = p[4] * np.exp(p[5] * v)
    k4 = p[6] * np.exp(-p[7] * v)
    a_inf = k1 / (k1 + k2)
    tau_a = 1 / (k1 + k2)
    r_inf = k4 / (k3 + k4)
    tau_r = 1 / (k3 + k4)
    da = (a_inf - a) / tau_a
    dr = (r_inf - r) / tau_r
    return [da,dr]

def observation(t, x, theta):
    # I
    a, r = x[:2]
    *ps, g = theta[:9]
    return g * a * r * (V(t) - EK)
# get Voltage for time in ms
def V(t):
    return volts_intepolated((t)/ 1000)

# main
if __name__ == '__main__':
    #  load the voltage data:
    volts = np.genfromtxt("./protocol-staircaseramp.csv", skip_header=1, dtype=float, delimiter=',')
    #  check when the voltage jumps
    # read the times and valued of voltage clamp
    volt_times, volts = np.genfromtxt("./protocol-staircaseramp.csv", skip_header=1, dtype=float, delimiter=',').T
    # interpolate with smaller time step (milliseconds)
    volts_intepolated = sp.interpolate.interp1d(volt_times, volts, kind='previous')

    # tlim = [0, int(volt_times[-1]*1000)]
    tlim = [0, 4600]
    times = np.linspace(*tlim, tlim[-1])
    # define a region of interest - we will need this to preserve the
    # trajectories of states given the full clamp and initial position, while
    ROI_start = 3300
    ROI_end = tlim[-1]
    ROI = range(ROI_start,ROI_end)
    # get time points to compute the fit to ODE cost
    times_roi = times[ROI_start:ROI_end]
    times_quad = np.linspace(times_roi[0], times_roi[-1],num=2*len(ROI)) # set up time nodes for quadrature integration
    volts_new = V(times)
    d2v_dt2 = np.diff(volts_new, n=2)
    dv_dt = np.diff(volts_new)
    der1_nonzero = np.abs(dv_dt) > 1e-6
    der2_nonzero = np.abs(d2v_dt2) > 1e-6
    switchpoints = [a and b for a, b in zip(der1_nonzero, der2_nonzero)]
    # ignore everything outside of the region of iterest
    switchpoints_roi = switchpoints[ROI_start:ROI_end]

    ## Generate the synthetic data
    # parameter values for the model
    EK = -80
    thetas_true = [2.26e-4, 0.0699, 3.45e-5, 0.05462, 0.0873, 8.91e-3, 5.15e-3, 0.03158, 0.1524]
    # initialise and solve ODE
    x0 = [0, 1]
    # solve initial value problem
    solution = sp.integrate.solve_ivp(ion_channel_model, tlim, x0, args=[thetas_true], dense_output=True,method='LSODA',rtol=1e-8,atol=1e-8)
    x_ar = solution.sol(times_roi)
    state_hidden_true = x_ar
    current_true = observation(times_roi, x_ar, thetas_true)

    ####################################################################################################################
    ## B-spline representation setup
    # set times of jumps and a B-spline knot sequence
    nPoints_closest = 24  # the number of points from each jump where knots are placed at the finest grid
    nPoints_between_closest = 8  # step between knots at the finest grid
    nPoints_around_jump = 48  # the time period from jump on which we place medium grid
    step_between_knots = 48  # this is the step between knots around the jump in the medium grid
    nPoints_between_jumps = 2  # this is the number of knots at the coarse grid corresponding to slowly changing values

    # get the times of all jumps
    a = [0] + [i + 1 for i, x in enumerate(switchpoints_roi) if x] + [
        len(ROI)]  # get indeces of all the switchpoints, add t0 and tend
    # remove consecutive numbers from the list
    b = []
    for i in range(len(a)):
        if len(b) == 0:  # if the list is empty, we add first item from 'a' (In our example, it'll be 2)
            b.append(a[i])
        else:
            if a[i] > a[i - 1] + 1:  # for every value of a, we compare the last digit from list b
                b.append(a[i])
    jump_indeces = b.copy()
    abs_distance_lists = [[(num - index) for num in range(len(ROI) + 1)] for index in
                          jump_indeces]  # compute absolute distance between each time and time of jump
    min_pos_distances = [min(filter(lambda x: x >= 0, lst)) for lst in zip(*abs_distance_lists)]
    max_neg_distances = [max(filter(lambda x: x <= 0, lst)) for lst in zip(*abs_distance_lists)]
    first_jump_index = np.where(np.array(min_pos_distances) == 0)[0][1]
    min_pos_distances[:first_jump_index] = [np.inf] * len(min_pos_distances[:first_jump_index])
    last_jump_index = np.where(np.array(max_neg_distances) == 0)[0][-2]
    max_neg_distances[last_jump_index:] = [-np.inf] * len(max_neg_distances[last_jump_index:])
    knots_after_jump = [
        ((x <= 2) and (x % 1 == 0)) or ((x <= nPoints_closest) and (x % nPoints_between_closest == 0)) or (
                (nPoints_closest <= x <= nPoints_around_jump) and (x % step_between_knots == 0)) for
        x in min_pos_distances]  # create a knot sequence that has higher density of knots after each jump
    # close_knots_duplicates = [(x <= 1) for x in min_pos_distances]
    # knots_before_jump = [((x >= -nPoints_closest) and (x % (nPoints_closest + 1) == 0)) for x in
    #                      max_neg_distances]  # list on knots befor each jump - use this form if you don't want fine grid before the jump
    knots_before_jump = [(x >= -1) for x in max_neg_distances]  # list on knots before each jump - add a fine grid
    knots_jump = [a or b for a, b in zip(knots_after_jump, knots_before_jump)]
    # add t0 and t_end as a single point in the end
    knots_jump[0] = True
    knots_jump[-1] = True  # logical sum for two boolean lists
    # to do this we then need to add additional coarse grid of knots between two jumps:
    knot_times = [i + ROI_start for i, x in enumerate(knots_jump) if x]
    # close_knots_duplicate_times = [i + ROI_start for i, x in enumerate(close_knots_duplicates) if x]
    # convert to numeric array again
    # add the final time point in case it is not already included - we need this if we are only adding values after steps
    if not np.isin(ROI_end, knot_times):
        knot_times.append(ROI_end)
    knots_all = knot_times.copy()  # + close_knots_duplicate_times.copy() # to see if having two splines tied to the close knots will improve precision
    for iKnot, timeKnot in enumerate(knot_times[:-1]):
        # add coarse grid knots between jumps
        if knot_times[iKnot + 1] - timeKnot > step_between_knots:
            # create evenly spaced points and drop start and end - those are already in the grid
            knots_between_jumps = np.rint(
                np.linspace(timeKnot, knot_times[iKnot + 1], num=nPoints_between_jumps + 2)[1:-1]).astype(int)
            # add indeces to the list
            knots_all = knots_all + list(knots_between_jumps)
        # add copies of the closest points to the jump
    knots_all.sort()  # sort list in ascending order - this is done inplace!

    # build the collocation matrix using the defined knot structure
    degree = 3
    fig, ax = plt.subplots()
    outer = [knots_all[0], knots_all[0], knots_all[0], knots_all[-1], knots_all[-1], knots_all[-1]]
    outer_y = []
    knots = np.insert(outer, 3, knots_all)  # create knots for which we want to build splines
    coeffs = np.zeros(len(knots) - degree - 1)  # number of splines will depend on the knot order
    spl_ones = BSpline(knots, np.ones_like(coeffs), degree)
    tau = np.arange(knots[0], knots[-1])
    splinest = [None] * len(coeffs)  # the grid of indtividual splines is required to generate a collocation matrix
    # fig, ax = plt.subplots()
    for i in range(len(coeffs)):
        tau_current = np.arange(knots[i], knots[i + 4])
        coeffs[i] = 1
        splinest[i] = BSpline(knots, coeffs.copy(), degree,
                              extrapolate=False)  # create a spline that only has one non-zero coeff
        # ax.plot(tau_current, splinest[i](tau_current), lw=0.5, alpha=0.7)
        coeffs[i] = 0
    collocation = collocm(splinest, tau)  # create a collocation matrix for that interval
    ####################################################################################################################
    ## Classes to run optimisation in pints
    nBsplineCoeffs = len(coeffs) * 2  # this to be used in params method of class ForwardModel
    print('Number of B-spline coeffs: ' + str(nBsplineCoeffs))
    nOutputs = 6
    # define a class that outputs only b-spline surface features
    class bsplineOutput(pints.ForwardModel):
        # this model outputs the discrepancy to be used in a rectangle quadrature scheme
        def simulate(self, parameters, times):
            # given times and return the simulated values
            coeffs_a, coeffs_r = np.split(parameters, 2)
            tck_a = (knots, coeffs_a, degree)
            tck_r = (knots, coeffs_r, degree)
            dot_a = sp.interpolate.splev(times, tck_a, der=1)
            dot_r = sp.interpolate.splev(times, tck_r, der=1)
            fun_a = sp.interpolate.splev(times, tck_a, der=0)
            fun_r = sp.interpolate.splev(times, tck_r, der=0)
            # the RHS must be put into an array
            dadr = ion_channel_model(times, [fun_a, fun_r], Thetas_ODE)
            rhs_theta = np.array(dadr)
            spline_surface = np.array([fun_a, fun_r])
            spline_deriv = np.array([dot_a, dot_r])
            # pack all required variables into the same array - will be the wrong orientation from pints preferred nTimes x nOutputs
            packed_output = np.concatenate((spline_surface,spline_deriv,rhs_theta),axis=0)
            return np.transpose(packed_output)

        def n_parameters(self):
            # Return the dimension of the parameter vector
            return nBsplineCoeffs

        def n_outputs(self):
            # Return the dimension of the output vector
            return nOutputs

    # define an error w.r.t B-spline parameters that assumes that it knows ODE parameters
    class InnerCriterion(pints.ProblemErrorMeasure):
        # do I need to redefine custom init or can just drop this part?
        def __init__(self, problem, weights=None):
            super(InnerCriterion, self).__init__(problem)
            if weights is None:
                weights = [1] * self._n_outputs
            elif self._n_outputs != len(weights):
                raise ValueError(
                    'Number of weights must match number of problem outputs.')
            # Check weights
            self._weights = np.asarray([float(w) for w in weights])
        # this function is the function of beta - bspline parameters
        def __call__(self, betas):
            # evaluate the integral at the value of B-spline coefficients
            model_output = self._problem.evaluate(betas)   # the output of the model with be an array of size nTimes x nOutputs
            x, x_dot, rhs = np.split(model_output, 3, axis=1) # we split the array into states, state derivs, and RHSs
            # compute the data fit
            *ps, g = Thetas_ODE[:9]
            volts_for_model = self._values[:,1] # we need to make sure that voltage is read at the times within ROI so we pass it in as part of values
            d_y = g * x[:, 0] * x[:, 1] * (volts_for_model - EK) - self._values[:,0]
            data_fit_cost = np.transpose(d_y) @ d_y
            # compute the gradient matching cost
            d_deriv = (x_dot - rhs) ** 2
            integral_quad = sp.integrate.simpson(y=d_deriv, even='avg',axis=0)
            gradient_match_cost = np.sum(integral_quad, axis=0)
            # not the most elegant implementation because it just grabs global lambda
            return data_fit_cost + lambd * gradient_match_cost

    # define a class that outputs only b-spline surface features
    class ODEOutput(pints.ForwardModel):
        # this model outputs the discrepancy to be used in a rectangle quadrature scheme
        def simulate(self, parameters, times):
            # given times and return the simulated values
            coeffs_a, coeffs_r = np.split(Betas_BSPL, 2)
            tck_a = (knots, coeffs_a, degree)
            tck_r = (knots, coeffs_r, degree)
            dot_a = sp.interpolate.splev(times, tck_a, der=1)
            dot_r = sp.interpolate.splev(times, tck_r, der=1)
            fun_a = sp.interpolate.splev(times, tck_a, der=0)
            fun_r = sp.interpolate.splev(times, tck_r, der=0)
            # the RHS must be put into an array
            dadr = ion_channel_model(times, [fun_a, fun_r], parameters) # this is what depends on the unkonw parameters now!
            rhs_theta = np.array(dadr)
            spline_surface = np.array([fun_a, fun_r])
            spline_deriv = np.array([dot_a, dot_r])
            # pack all required variables into the same array - will be the wrong orientation from pints preferred nTimes x nOutputs
            packed_output = np.concatenate((spline_surface, spline_deriv, rhs_theta), axis=0)
            return np.transpose(packed_output)

        def n_parameters(self):
            # Return the dimension of the parameter vector
            return nBsplineCoeffs

        def n_outputs(self):
            # Return the dimension of the output vector
            return nOutputs

    # define an error w.r.t ODE parameters that assumes that it knows B-spline parameters
    class OuterCriterion(pints.ProblemErrorMeasure):
        # do I need to redefine custom init or can just drop this part?
        def __init__(self, problem, weights=None):
            super(OuterCriterion, self).__init__(problem)
            if weights is None:
                weights = [1] * self._n_outputs
            elif self._n_outputs != len(weights):
                raise ValueError(
                    'Number of weights must match number of problem outputs.')
            # Check weights
            self._weights = np.asarray([float(w) for w in weights])
        # this function is the function of theta - ODE parameters
        def __call__(self, thetas):
            # read the ode coefficients from input
            *ps, g = thetas[:9]
            # evaluate the integral at the value of ODE parameters
            model_output = self._problem.evaluate(thetas)   # the output of the model with be an array of size nTimes x nOutputs
            x, x_dot, rhs = np.split(model_output, 3, axis=1) # we split the array into states, state derivs, and RHSs
            # compute the data fit
            volts_for_model = self._values[:,1] # we need to make sure that voltage is read at the times within ROI so we pass it in as part of values
            d_y = g * x[:, 0] * x[:, 1] * (volts_for_model - EK) - self._values[:,0] # this part depends on theta_g
            data_fit_cost = np.transpose(d_y) @ d_y
            # compute the gradient matching cost
            d_deriv = (x_dot - rhs) ** 2
            integral_quad = sp.integrate.simpson(y=d_deriv, even='avg',axis=0)
            gradient_match_cost = np.sum(integral_quad, axis=0)
            # not the most elegant implementation because it just grabs global lambda
            return data_fit_cost + lambd * gradient_match_cost
    ####################################################################################################################
    ## Run the optimisation
    lambd = 0.5
    nThetas = len(thetas_true)
    init_thetas = 0.001 * np.ones(nThetas) #initial values for ODE parameters
    sigma0_thetas = 0.0005 * np.ones(nThetas)
    init_betas = 0.5 * np.ones(nBsplineCoeffs) # initial values of B-spline coefficients
    sigma0_betas = 0.2 * np.ones(nBsplineCoeffs)
    tic = tm.time()
    model_bsplines = bsplineOutput()
    model_ode = ODEOutput()
    ## create the problem of comparing the modelled current with measured current
    voltage = V(times_roi) # must read voltage at the correct times to match the output
    values_to_match_output_dims = np.transpose(np.array([current_true,voltage,current_true,voltage,current_true,voltage]))
    #^ we actually only need first two columns in this array but pints wants to have the same number of values and outputs
    problem_inner = pints.MultiOutputProblem(model=model_bsplines, times=times_roi, values=values_to_match_output_dims)
    problem_outer = pints.MultiOutputProblem(model=model_ode, times=times_roi, values=values_to_match_output_dims)
    ## associate the cost with it
    error_inner  = InnerCriterion(problem=problem_inner)
    error_outer = OuterCriterion(problem=problem_outer)
    ##  define boundaries for the inner optimisation
    boundaries_betas = pints.RectangularBoundaries(np.zeros_like(init_betas),0.99 * np.ones_like(init_betas))
    ## define boundaries for the outer optimisation
    boundaries_thetas = pints.RectangularBoundaries(np.zeros_like(init_thetas), np.ones_like(init_thetas))
    ####################################################################################################################
    # fit B-spline coefficients to the hidden state directly
    coeffs_ls = np.dot((np.dot(np.linalg.pinv(np.dot(collocation, collocation.T)), collocation)), state_hidden_true.T)
    Betas_BSPL = coeffs_ls.T.flatten()
    Thetas_ODE = thetas_true.copy()
    InnerCost_true = error_inner(Betas_BSPL)
    OuterCost_true = error_outer(Thetas_ODE)
    Betas_BSPL_fit_to_true_states = Betas_BSPL.copy()
    ## get inner cirterion at true ODE param values assuming Betas are unkown
    optimiser_inner = pints.OptimisationController(error_inner, x0=init_betas, sigma0=sigma0_betas,
                                                   boundaries=boundaries_betas, method=pints.CMAES)
    optimiser_inner.set_max_iterations(30000)
    optimiser_inner.set_max_unchanged_iterations(iterations=50, threshold=1e-7)
    optimiser_inner.set_parallel(False)
    optimiser_inner.set_log_to_screen(True)
    Betas_BSPL_given_true_theta, InnerCost_given_true_theta = optimiser_inner.run()
    OuterCost_given_true_theta = error_outer(Thetas_ODE)

    model_output_fit_to_state = model_bsplines.simulate(Betas_BSPL_fit_to_true_states, times_roi)
    state_direct, state_deriv_direct, rhs_direct = np.split(model_output_fit_to_state, 3, axis=1)
    model_output_fit_at_truth = model_bsplines.simulate(Betas_BSPL_given_true_theta, times_roi)
    state_at_truth, state_deriv_at_truth, rhs_truth = np.split(model_output_fit_at_truth, 3, axis=1)
    *ps, g = Thetas_ODE
    current_model_direct = g * state_direct[:, 0] * state_direct[:,1] * (voltage - EK)
    current_model_at_truth = g * state_at_truth[:, 0] * state_at_truth[:,1] * (voltage - EK)
    fig, axes = plt.subplot_mosaic([['a)', 'a)'], ['b)', 'c)'], ['d)', 'e)']], layout='constrained')
    # fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    y_labels = ['I', '$\dot{a}$', '$\dot{r}$', '$a$', '$r$']
    axes['a)'].plot(times_roi, current_true, '-k', label=r'Current true', linewidth=2, alpha=0.7)
    axes['a)'].plot(times_roi, current_model_direct, '--r', label=r'Fit to state directly')
    axes['a)'].plot(times_roi, current_model_at_truth, '--b', label=r'Optimised given true $\theta$')
    axes['b)'].plot(times_roi[:], rhs_direct[:,0], '-k', label='$\dot{a}$ fit directly', linewidth=2, alpha=0.7)
    axes['b)'].plot(times_roi[:], state_deriv_direct[:,0], '--r', label=r'B-spline derivative fit directly')
    axes['b)'].plot(times_roi[:], rhs_truth[:,0], '-m', label=r'$\dot{a}$ given true $\theta$', linewidth=2, alpha=0.7)
    axes['b)'].plot(times_roi[:], state_deriv_at_truth[:,0], '--b', label=r'B-spline derivative given true $\theta$')
    axes['c)'].plot(times_roi[:], rhs_direct[:,1], '-k', label='$\dot{r}$ fit directly', linewidth=2, alpha=0.7)
    axes['c)'].plot(times_roi[:], state_deriv_direct[:,1], '--r', label=r'B-spline derivative fit directly')
    axes['c)'].plot(times_roi[:], rhs_truth[:,1], '-m', label=r'$\dot{r}$ given true $\theta$', linewidth=2, alpha=0.7)
    axes['c)'].plot(times_roi[:], state_deriv_at_truth[:,1], '--b', label=r'B-spline derivative given true $\theta$')
    axes['d)'].plot(times_roi, state_hidden_true[0, :], '-k', label=r'$a$ true', linewidth=2, alpha=0.7)
    axes['d)'].plot(times_roi, state_direct[:, 0], '--r', label=r'B-spline approximation direct fit')
    axes['d)'].plot(times_roi, state_at_truth[:, 0], '--b', label=r'B-spline approximation given true $\theta$')
    axes['e)'].plot(times_roi, state_hidden_true[1, :], '-k', label=r'$r$ true', linewidth=2, alpha=0.7)
    axes['e)'].plot(times_roi, state_direct[:, 1], '--r', label=r'B-spline approximation direct fit')
    axes['e)'].plot(times_roi, state_at_truth[:, 1], '--b', label=r'B-spline approximation given true $\theta$')
    iAx = 0
    for _, ax in axes.items():
        # ax.set_xlim([3380,3420])
        ax.set_ylabel(y_labels[iAx], fontsize=12)
        ax.legend(fontsize=12, loc='best')
        iAx +=1
    # ax.set_xlabel('time,ms', fontsize=12)
    # plt.tight_layout(pad=0.3)
    # plt.ioff()
    plt.savefig('Figures/cost_terms_at_truth.png', dpi=600)
    ####################################################################################################################
    # This algorithm is loosely based on ask-tel example from  pints
    convergence_threshold = 1e-5
    iter_for_convergence = 50
    # Create an outer optimisation object
    big_tic = tm.time()
    optimiser_outer = pints.CMAES(x0=init_thetas,sigma0=sigma0_thetas, boundaries=boundaries_thetas)
    optimiser_outer.set_population_size(min(len(Thetas_ODE) * 5, 25))
    ## Run optimisation
    theta_visited = []
    theta_guessed = []
    f_guessed = []
    theta_best = []
    f_best = []
    InnerCosts_all = []
    OuterCosts_all = []
    for i in range(500):
        # get the next points (multiple locations)
        thetas = optimiser_outer.ask()
        # create the placeholder for cost functions
        OuterCosts = []
        InnerCosts = []
        # for each theta in the sample
        tic = tm.time()
        for theta in thetas:
            # assign the variable that is readable in the class of B-spline evaluation
            Thetas_ODE = theta.copy()
            # fit the b-spline surface given the sampled value of the ODE parameter vector
            # introduce an optimiser every time beacause it does not understand why thre is already an instance of the optimier
            optimiser_inner = pints.OptimisationController(error_inner, x0=init_betas, boundaries=boundaries_betas,
                                                           method=pints.CMAES)
            optimiser_inner.set_max_iterations(30000)
            optimiser_inner.set_max_unchanged_iterations(iterations=50, threshold=1e-6)
            optimiser_inner.set_parallel(False)
            optimiser_inner.set_log_to_screen(False)
            Betas_BSPL, InnerCost = optimiser_inner.run()
            # init_betas = Betas_BSPL # update the init conds for the next itimiser instance
            # evaluate the cost function at the sampled value of ODE parameter vector
            InnerCosts.append(InnerCost)
            OuterCosts.append(error_outer(theta))
            del Thetas_ODE  # make sure this is updated
        # feed the evaluated scores into the optimisation object
        optimiser_outer.tell(OuterCosts)
        toc = tm.time()
        print(str(i) + '-th iteration finished. Elapsed time: ' + str(toc - tic) + 's')
        # store all costs in the lists
        InnerCosts_all.append(InnerCosts)
        OuterCosts_all.append(OuterCosts)
        # HOW DO I CHECK CONVERGENCE HERE - for all points of average cost???
        # Store the requested points
        theta_visited.extend(thetas)
        # Store the current guess
        theta_g = np.mean(thetas, axis=0)
        theta_guessed.append(theta_g)
        f_guessed.append(error_outer(theta_g))
        # Store the accompanying score
        # Store the best position and score seen so far
        index_best = OuterCosts.index(min(OuterCosts))
        theta_best.append(thetas[index_best, :])
        f_best.append(OuterCosts[index_best])
        # the most basic convergence condition after running first fifty
        if (i > iter_for_convergence):
            # check how the cost increment changed over the last 10 iterations
            d_cost = np.diff(f_best[-iter_for_convergence:])
            # if all incrementa are below a threshold break the loop
            if all(d <= convergence_threshold for d in d_cost):
                print("No changes in" + str(iter_for_convergence) + "iterations. Terminating")
                break
    # convert lists into arrays
    theta_visited = np.array(theta_visited)
    theta_guessed = np.array(theta_guessed)
    theta_best = np.array(theta_best)
    f_best = np.array(f_best)
    f_guessed = np.array(f_guessed)
    big_toc = tm.time()
    print('Optimisation finished. Elapsed time: ' + str(big_toc - big_tic) + 's')
    ####################################################################################################################
    # try saving the results
    results_to_save = [InnerCosts_all, OuterCosts_all, theta_visited, theta_guessed, theta_best, f_guessed, f_best]
    with open("ask_tell_iterations.pkl", "wb") as output_file:
        pkl.dump(results_to_save, output_file)
    ####################################################################################################################
    # plot evolution of outer costs
    plt.figure()
    plt.semilogy()
    plt.xlabel('Iteration')
    plt.ylabel('Outer optimisation cost')
    for iter in range(len(f_best)):
        plt.scatter(iter * np.ones(len(InnerCosts_all[iter])), InnerCosts_all[iter], c='k', marker='.', alpha=.5,
                    linewidths=0)
    plt.plot(range(iter), np.ones(iter) * InnerCost_true, '-m', linewidth=2.5, alpha=.5, label='Cost at truth')
    plt.legend(loc='best')
    plt.tight_layout()
    plt.savefig('Figures/inner_cost_ask_tell_dif_costs.png')

    # plot evolution of inner costs
    plt.figure()
    plt.semilogy()
    plt.xlabel('Iteration')
    plt.ylabel('Inner optimisation cost')
    for iter in range(len(f_best)):
        plt.scatter(iter * np.ones(len(OuterCosts_all[iter])), OuterCosts_all[iter], c='k', marker='.', alpha=.5,
                    linewidths=0)
    plt.plot(range(iter), np.ones(iter) * OuterCost_true, '-m', linewidth=2.5, alpha=.5, label='Cost at truth')
    plt.plot(f_best, '-b', linewidth=1.5, label='Best cost')
    plt.legend(loc='best')
    plt.tight_layout()
    plt.savefig('Figures/outer_cost_ask_tell_dif_costs.png')

    # plot parameter values
    fig, axes = plt.subplots(3, 3, figsize=(20, 8), sharex=True)
    n_walkers = int(theta_visited.shape[0] / len(theta_best))
    for iAx, ax in enumerate(axes.flatten()):
        for iter in range(len(theta_best)):
            x_visited_iter = theta_visited[iter * n_walkers:(iter + 1) * n_walkers, iAx]
            ax.scatter(iter * np.ones(len(x_visited_iter)), x_visited_iter, c='k', marker='.', alpha=.2,
                       linewidth=0)
        ax.plot(range(iter), np.ones(iter) * p_true[iAx], '-m', linewidth=2.5, alpha=.5, label='true')
        ax.plot(theta_guessed[:, iAx], '--r', linewidth=1.5, label='guessed')
        ax.plot(theta_best[:, iAx], '-b', linewidth=1.5, label='best')
        ax.set_ylabel('$p_{' + str(iAx) + '}$')
    ax.legend(loc='best')
    plt.tight_layout()
    plt.savefig('Figures/ODE_params_ask_tell_dif_costs.png')

    # plot model output
    current_true = observation(times_roi, x_ar, p_true)
    Thetas_ODE = theta_best[-1, :]
    optimiser_inner = pints.OptimisationController(error_inner, x0=init_betas, boundaries=boundaries_betas,
                                                   method=pints.CMAES)
    optimiser_inner.set_max_iterations(30000)
    optimiser_inner.set_max_unchanged_iterations(iterations=50, threshold=1e-6)
    optimiser_inner.set_parallel(False)
    optimiser_inner.set_log_to_screen(False)
    Betas_BSPL, BSPL_cost = optimiser_inner.run()
    opt_model_output = model_bsplines.simulate(Betas_BSPL, times_roi)
    states, state_derivs, rhs = np.split(opt_model_output, 3, axis=1)
    *ps, g = Thetas_ODE[:9]
    current_model = g * states[:, 0] * states[:, 1] * (voltage - EK)
    fig, axes = plt.subplots(2, 3)
    y_labels = ['I', '$\dot{a}$', '$\dot{r}$', 'a', 'r']
    axes[0, 2].plot(times_roi, current_true, '-k', label='Current true')
    axes[0, 2].plot(times_roi, current_model, '--r', label='Optimised model output')
    axes[0, 0].plot(times_roi, rhs[:, 0], '-k', label='$\dot{a}$')
    axes[0, 0].plot(times_roi, state_derivs[:, 0], '--r', label='B-spline derivative')
    axes[0, 1].plot(times_roi, rhs[:, 1], '-k', label='$\dot{r}$')
    axes[0, 1].plot(times_roi, state_derivs[:, 1], '--r', label='B-spline derivative')
    axes[1, 0].plot(times_roi, x_ar[0, :], '-k', label=y_labels[3] + ' true')
    axes[1, 0].plot(times_roi, states[:, 0], '--r', label='B-spline approximation')
    axes[1, 1].plot(times_roi, x_ar[1, :], '-k', label=y_labels[4] + ' true')
    axes[1, 1].plot(times_roi, states[:, 1], '--r', label='B-spline approximation')
    for iAx, ax in enumerate(axes.flatten()[:-1]):
        ax.set_xlabel('time,ms', fontsize=12)
        ax.legend(fontsize=12, loc='lower right')
    #     ax.set_ylabel(y_labels[iAx],fontsize=8)
    plt.tight_layout(pad=0.3)
    # plt.ioff()
    plt.savefig('Figures/cost_terms_ask_tell_dif_costs.png')
    ####################################################################################################################
    print('pause here')