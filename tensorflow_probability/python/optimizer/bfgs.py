# Copyright 2018 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""The Broyden-Fletcher-Goldfarb-Shanno minimization algorithm.

Quasi Newton methods are a class of popular first order optimization algorithm.
These methods use a positive definite approximation to the exact
Hessian to find the search direction. The Broyden-Fletcher-Goldfarb-Shanno
algorithm (BFGS) is a specific implementation of this general idea.

This module provides an implementation of the BFGS scheme using the Hager Zhang
line search method.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections

# Dependency imports
import numpy as np
import tensorflow as tf

from tensorflow_probability.python.optimizer import linesearch
from tensorflow.python.framework import smart_cond


BfgsOptimizerResults = collections.namedtuple(
    'BfgsOptimizerResults', [
        'converged',  # Scalar boolean tensor indicating whether the minimum
                      # was found within tolerance.
        'failed',  # Scalar boolean tensor indicating whether a line search
                   # step failed to find a suitable step size satisfying Wolfe
                   # conditions. In the absence of any constraints on the
                   # number of objective evaluations permitted, this value will
                   # be the complement of `converged`. However, if there is
                   # a constraint and the search stopped due to available
                   # evaluations being exhausted, both `failed` and `converged`
                   # will be simultaneously False.
        'num_iterations',  # The number of iterations of the BFGS update.
        'num_objective_evaluations',  # The total number of objective
                                      # evaluations performed.
        'position',  # A tensor containing the last argument value found
                     # during the search. If the search converged, then
                     # this value is the argmin of the objective function.
        'objective_value',  # A tensor containing the value of the objective
                            # function at the `position`. If the search
                            # converged, then this is the (local) minimum of
                            # the objective function.
        'objective_gradient',  # A tensor containing the gradient of the
                               # objective function at the
                               # `final_position`. If the search converged
                               # this L2-norm of this tensor should be
                               # below the tolerance.
        'inverse_hessian_estimate'  # A tensor containing the inverse of the
                                    # estimated Hessian.
    ])


def minimize(value_and_gradients_function,
             initial_position,
             tolerance=1e-8,
             x_tolerance=0,
             f_relative_tolerance=0,
             initial_inverse_hessian_estimate=None,
             max_iterations=50,
             parallel_iterations=1,
             name=None):
  """Applies the BFGS algorithm to minimize a differentiable function.

  Performs unconstrained minimization of a differentiable function using the
  BFGS scheme. For details of the algorithm, see [Nocedal and Wright(2006)][1].

  ### Usage:

  The following example demonstrates the BFGS optimizer attempting to find the
  minimum for a simple two dimensional quadratic objective function.

  ```python
    minimum = np.array([1.0, 1.0])  # The center of the quadratic bowl.
    scales = np.array([2.0, 3.0])  # The scales along the two axes.

    # The objective function and the gradient.
    def quadratic(x):
      value = tf.reduce_sum(scales * (x - minimum) ** 2)
      return value, tf.gradients(value, x)[0]

    start = tf.constant([0.6, 0.8])  # Starting point for the search.
    optim_results = tfp.optimizer.bfgs_minimize(
        quadratic, initial_position=start, tolerance=1e-8)

    with tf.Session() as session:
      results = session.run(optim_results)
      # Check that the search converged
      assert(results.converged)
      # Check that the argmin is close to the actual value.
      np.testing.assert_allclose(results.position, minimum)
      # Print out the total number of function evaluations it took. Should be 6.
      print ("Function evaluations: %d" % results.num_objective_evaluations)
  ```

  ### References:
  [1]: Jorge Nocedal, Stephen Wright. Numerical Optimization. Springer Series in
    Operations Research. pp 136-140. 2006
    http://pages.mtu.edu/~struther/Courses/OLD/Sp2013/5630/Jorge_Nocedal_Numerical_optimization_267490.pdf

  Args:
    value_and_gradients_function:  A Python callable that accepts a point as a
      real `Tensor` and returns a tuple of `Tensor`s of real dtype containing
      the value of the function and its gradient at that point. The function
      to be minimized. The first component of the return value should be a
      real scalar `Tensor`. The second component (the gradient) should have the
      same shape as the input value to the function.
    initial_position: `Tensor` of real dtype. The starting point of the search
      procedure. Should be a point at which the function value and the gradient
      norm are finite.
    tolerance: Scalar `Tensor` of real dtype. Specifies the gradient tolerance
      for the procedure. If the supremum norm of the gradient vector is below
      this number, the algorithm is stopped.
    x_tolerance: Scalar `Tensor` of real dtype. If the absolute change in the
      position between one iteration and the next is smaller than this number,
      the algorithm is stopped.
    f_relative_tolerance: Scalar `Tensor` of real dtype. If the relative change
      in the objective value between one iteration and the next is smaller
      than this value, the algorithm is stopped.
    initial_inverse_hessian_estimate: Optional `Tensor` of the same dtype
      as the components of the output of the `value_and_gradients_function`.
      If specified, the shape should be `initial_position.shape` * 2.
      For example, if the shape of `initial_position` is `[n]`, then the
      acceptable shape of `initial_inverse_hessian_estimate` is as a square
      matrix of shape `[n, n]`.
      If the shape of `initial_position` is `[n, m]`, then the required shape
      is `[n, m, n, m]`.
      For the correctness of the algorithm, it is required that this parameter
      be symmetric and positive definite. Specifies the starting estimate for
      the inverse of the Hessian at the initial point. If not specified,
      the identity matrix is used as the starting estimate for the
      inverse Hessian.
    max_iterations: Scalar positive int32 `Tensor`. The maximum number of
      iterations for BFGS updates.
    parallel_iterations: Positive integer. The number of iterations allowed to
      run in parallel.
    name: (Optional) Python str. The name prefixed to the ops created by this
      function. If not supplied, the default name 'minimize' is used.

  Returns:
    optimizer_results: A namedtuple containing the following items:
      converged: Scalar boolean tensor indicating whether the minimum was
        found within tolerance.
      failed:  Scalar boolean tensor indicating whether a line search
        step failed to find a suitable step size satisfying Wolfe
        conditions. In the absence of any constraints on the
        number of objective evaluations permitted, this value will
        be the complement of `converged`. However, if there is
        a constraint and the search stopped due to available
        evaluations being exhausted, both `failed` and `converged`
        will be simultaneously False.
      num_objective_evaluations: The total number of objective
        evaluations performed.
      position: A tensor containing the last argument value found
        during the search. If the search converged, then
        this value is the argmin of the objective function.
      objective_value: A tensor containing the value of the objective
        function at the `position`. If the search converged, then this is
        the (local) minimum of the objective function.
      objective_gradient: A tensor containing the gradient of the objective
        function at the `position`. If the search converged this
        L2-norm of this tensor should be below the tolerance.
      inverse_hessian_estimate: A tensor containing the inverse of the
        estimated Hessian.
  """
  with tf.name_scope(name, 'minimize', [initial_position,
                                        tolerance,
                                        initial_inverse_hessian_estimate]):
    initial_position = tf.convert_to_tensor(initial_position,
                                            name='initial_position')
    dtype = initial_position.dtype.base_dtype
    tolerance = tf.convert_to_tensor(tolerance, dtype=dtype,
                                     name='grad_tolerance')
    f_relative_tolerance = tf.convert_to_tensor(f_relative_tolerance,
                                                dtype=dtype,
                                                name='f_relative_tolerance')
    x_tolerance = tf.convert_to_tensor(x_tolerance,
                                       dtype=dtype,
                                       name='x_tolerance')
    max_iterations = tf.convert_to_tensor(max_iterations, name='max_iterations')

    domain_shape = tf.shape(initial_position)

    if initial_inverse_hessian_estimate is None:
      inv_hessian_shape = tf.concat((domain_shape, domain_shape), 0)
      initial_inv_hessian = tf.eye(tf.size(initial_position), dtype=dtype)
      initial_inv_hessian = tf.reshape(initial_inv_hessian,
                                       inv_hessian_shape,
                                       name='initial_inv_hessian')
    else:
      initial_inv_hessian = tf.convert_to_tensor(
          initial_inverse_hessian_estimate,
          dtype=dtype,
          name='initial_inv_hessian')

    # If an initial inverse Hessian is supplied, ensure that it is positive
    # definite. The easiest way to validate this is to compute the Cholesky
    # decomposition. However, it seems that simply adding a control dependency
    # on the decomposition result is not enough to trigger it. We need to
    # add an assert on the result.
    if initial_inverse_hessian_estimate is not None:
      # The supplied Hessian may not be of rank 2. Reshape it so it is.
      initial_inv_hessian_sqr_mat = tf.reshape(
          initial_inverse_hessian_estimate,
          tf.stack([tf.size(initial_position),
                    tf.size(initial_position)], axis=0))
      # If the matrix is not positive definite, the Cholesky decomposition will
      # fail. Adding an assert on it ensures it will be triggered.
      cholesky_factor = tf.cholesky(initial_inv_hessian_sqr_mat)
      is_positive_definite = tf.reduce_all(tf.is_finite(cholesky_factor))
      asymmetry = tf.norm(initial_inv_hessian_sqr_mat -
                          tf.transpose(initial_inv_hessian_sqr_mat), np.inf)
      is_symmetric = tf.equal(asymmetry, 0)
      with tf.control_dependencies(
          [tf.Assert(is_positive_definite,
                     ['Initial inverse Hessian is not positive definite.',
                      initial_inverse_hessian_estimate]),
           tf.Assert(is_symmetric,
                     ['Initial inverse Hessian is not symmetric',
                      initial_inverse_hessian_estimate])]):
        f0, df0 = value_and_gradients_function(initial_position)
    else:
      f0, df0 = value_and_gradients_function(initial_position)

    initial_convergence = _initial_convergence_test(df0, tolerance)

    def _cond(converged,
              failed,
              iteration,
              *ignored_args):  # pylint: disable=unused-argument
      """Stopping condition for the algorithm."""
      keep_going = tf.logical_not(converged | failed |
                                  (iteration >= max_iterations))
      return keep_going

    def _body(converged,  # pylint: disable=unused-argument
              stopped,  # pylint: disable=unused-argument
              iteration,
              total_evals,
              position,
              objective_value,
              objective_gradient,
              input_inv_hessian_estimate):
      """Main optimization loop."""

      search_direction = _get_search_direction(input_inv_hessian_estimate,
                                               objective_gradient)
      derivative_at_start_pt = tf.reduce_sum(objective_gradient *
                                             search_direction)
      # If the derivative at the start point is not negative, reset the
      # Hessian estimate and recompute the search direction.
      needs_reset = derivative_at_start_pt >= 0
      def _reset_search_dirn():
        search_direction = _get_search_direction(initial_inv_hessian,
                                                 objective_gradient)
        return search_direction, initial_inv_hessian

      search_direction, inv_hessian_estimate = smart_cond.smart_cond(
          needs_reset,
          true_fn=_reset_search_dirn,
          false_fn=lambda: (search_direction, input_inv_hessian_estimate))
      line_search_value_grad_func = _restrict_along_direction(
          value_and_gradients_function, position, search_direction)
      derivative_at_start_pt = tf.reduce_sum(objective_gradient *
                                             search_direction)

      ls_result = linesearch.hager_zhang(
          line_search_value_grad_func,
          initial_step_size=tf.convert_to_tensor(1, dtype=dtype),
          objective_at_zero=objective_value,
          grad_objective_at_zero=derivative_at_start_pt)

      # Fail if the objective value is not finite or the line search failed.
      ls_failed = ~ls_result.converged

      # If the line search failed, then quit at this point.
      def _failed_fn():
        """Line search failed action."""
        failed_retval = BfgsOptimizerResults(
            converged=False,
            failed=True,
            num_iterations=iteration + 1,
            num_objective_evaluations=total_evals + ls_result.func_evals,
            position=position,
            objective_value=objective_value,
            objective_gradient=objective_gradient,
            inverse_hessian_estimate=inv_hessian_estimate)
        return failed_retval

      def _success_fn():
        return _bfgs_update(value_and_gradients_function,
                            position,
                            objective_value,
                            objective_gradient,
                            search_direction,
                            inv_hessian_estimate,
                            ls_result.left_pt,
                            iteration,
                            total_evals + ls_result.func_evals,
                            tolerance,
                            f_relative_tolerance,
                            x_tolerance)

      return smart_cond.smart_cond(ls_failed,
                                   true_fn=_failed_fn,
                                   false_fn=_success_fn)

    initial_values = BfgsOptimizerResults(
        converged=initial_convergence,
        failed=False,
        num_iterations=0,
        num_objective_evaluations=1,
        position=initial_position,
        objective_value=f0,
        objective_gradient=df0,
        inverse_hessian_estimate=initial_inv_hessian)

    return tf.while_loop(_cond, _body, initial_values,
                         parallel_iterations=parallel_iterations)


_UpdatedPosition = collections.namedtuple('_UpdatedPosition', [
    'failed',
    'position_delta',
    'gradient_delta',
    'next_position',
    'next_value',
    'next_gradient',
    'evals'])


def _is_finite(arg1, *args):
  """Checks if the supplied tensors are finite.

  Args:
    arg1: A numeric `Tensor`.
    *args: (Optional) Other `Tensors` to check for finiteness.

  Returns:
    is_finite: Scalar boolean `Tensor` indicating whether all the supplied
      tensors are finite.
  """
  finite = tf.reduce_all(tf.is_finite(arg1))
  for arg in args:
    finite = finite & tf.reduce_all(tf.is_finite(arg))
  return finite


def _bfgs_update(value_and_gradients_function,
                 current_position,
                 current_objective,
                 current_gradient,
                 search_direction,
                 current_inverse_hessian,
                 step_size,
                 iteration,
                 num_evaluations,
                 grad_tolerance,
                 f_relative_tolerance,
                 x_tolerance):
  """Perform a BFGS update."""
  updated = _update_position(value_and_gradients_function,
                             current_position,
                             current_gradient,
                             search_direction,
                             step_size)

  # Check for convergence.
  converged = _check_convergence(current_position,
                                 updated.next_position,
                                 current_objective,
                                 updated.next_value,
                                 updated.next_gradient,
                                 grad_tolerance,
                                 f_relative_tolerance,
                                 x_tolerance)
  # If not converged, update the Hessian.
  def _update_hessian():
    return _bfgs_inv_hessian_update(updated.gradient_delta,
                                    updated.position_delta,
                                    current_inverse_hessian)

  next_inverse_hessian = smart_cond.smart_cond(
      converged,
      lambda: current_inverse_hessian,
      _update_hessian)

  return BfgsOptimizerResults(
      converged=converged,
      failed=updated.failed,
      num_iterations=iteration + 1,
      num_objective_evaluations=num_evaluations + updated.evals,
      position=updated.next_position,
      objective_value=updated.next_value,
      objective_gradient=updated.next_gradient,
      inverse_hessian_estimate=next_inverse_hessian)


def _update_position(value_and_gradients_function,
                     position,
                     gradient,
                     search_direction,
                     step_size):
  """Perform a step of the BFGS update.

  Args:
    value_and_gradients_function: The objective function.
    position: The current position.
    gradient: The current gradient.
    search_direction: The direction of the search.
    step_size: The size of the step to take along the search direction.

  Returns:
    A named tuple containing the following fields
      failed: Indicates whether the update failed.
      position_delta: The change in the position.
      gradient_delta: The change in the derivative.
      next_position: The next position.
      next_value: The value of the objective function at the next position.
      next_gradient: The gradient of the objective function at the next
        position.
      evals: The number of evaluations made.
  """
  position_delta = search_direction * step_size
  next_position = position + position_delta
  next_objective, next_gradient = value_and_gradients_function(
      next_position)

  grad_delta = next_gradient - gradient
  return _UpdatedPosition(
      failed=~_is_finite(next_objective, next_gradient),
      position_delta=position_delta,
      gradient_delta=grad_delta,
      next_position=next_position,
      next_value=next_objective,
      next_gradient=next_gradient,
      evals=1)


def _check_convergence(current_position,
                       next_position,
                       current_objective,
                       next_objective,
                       next_gradient,
                       grad_tolerance,
                       f_relative_tolerance,
                       x_tolerance):
  """Checks if the algorithm satisfies the convergence criteria."""
  norm = lambda x: tf.norm(x, np.inf)
  grad_converged = norm(next_gradient) <= grad_tolerance
  x_converged = norm(next_position - current_position) <= x_tolerance
  f_converged = (norm(next_objective - current_objective) <=
                 f_relative_tolerance * current_objective)
  return grad_converged | x_converged | f_converged


def _initial_convergence_test(gradient, tolerance):
  """Checks whether the gradient is below the supplied tolerance."""
  return tf.norm(gradient, ord=np.inf) < tolerance


def _get_search_direction(inv_hessian_approx, gradient):
  """Computes the direction along which to perform line search."""
  n = len(gradient.shape.as_list())
  contraction_axes = np.arange(-n, 0)
  dirn = -tf.tensordot(inv_hessian_approx, gradient,
                       axes=[contraction_axes, contraction_axes])
  dirn.set_shape(gradient.shape)
  return dirn


def _restrict_along_direction(value_and_gradients_function,
                              position,
                              direction):
  """Restricts a function in n-dimensions to a given direction.

  Suppose f: R^n -> R. Then given a point x0 and a vector p0 in R^n, the
  restriction of the function along that direction is defined by:

  ```None
  g(t) = f(x0 + t * p0)
  ```

  This function performs this restriction on the given function. In addition, it
  also computes the gradient of the restricted function along the restriction
  direction. This is equivalent to computing `dg/dt` in the definition above.

  Args:
    value_and_gradients_function: Callable accepting a single `Tensor` argument
      of real dtype and returning a tuple of a scalar real `Tensor` and a
      `Tensor` of same shape as the input argument. The multivariate function
      whose restriction is to be computed. The output values of the callable are
      the function value and the gradients at the input argument.
    position: `Tensor` of real dtype and shape consumable by
      `value_and_gradients_function`. Corresponds to `x0` in the definition
      above.
    direction: `Tensor` of the same dtype and shape as `position`. The direction
      along which to restrict the function. Note that the direction need not
      be a unit vector.

  Returns:
    restricted_value_and_gradients_func: A callable accepting a scalar tensor
      of same dtype as `position` and returning a tuple of `Tensors`. The
      input tensor is the parameter along the direction labelled `t` above. The
      first element of the return tuple is a scalar `Tensor` containing
      the value of the function at the point `position + t * direction`. The
      second element is also a scalar `Tensor` of the same dtype as `position`.
  """
  def _restricted_func(t):
    pt = position + t * direction
    objective_value, gradient = value_and_gradients_function(pt)
    return objective_value, tf.reduce_sum(gradient * direction)
  return _restricted_func


def _bfgs_inv_hessian_update(grad_delta,
                             position_delta,
                             inv_hessian_estimate):
  """Applies the BFGS update to the inverse Hessian estimate.

  The BFGS update rule is (note A^T denotes the transpose of a vector/matrix A).

  ```None
    rho = 1/(grad_delta^T * position_delta)
    U = (I - rho * position_delta * grad_delta^T)
    H_1 =  U * H_0 * U^T + rho * position_delta * position_delta^T
  ```

  Here, `H_0` is the inverse Hessian estimate at the previous iteration and
  `H_1` is the next estimate. Note that `*` should be interpreted as the
  matrix multiplication (with the understanding that matrix multiplication for
  scalars is usual multiplication and for matrix with vector is the action of
  the matrix on the vector.).

  The implementation below utilizes an expanded version of the above formula
  to avoid the matrix multiplications that would be needed otherwise. By
  expansion it is easy to see that one only needs matrix-vector or
  vector-vector operations. The expanded version is:

  ```None
    f = 1 + rho * (grad_delta^T * H_0 * grad_delta)
    H_1 - H_0 = - rho * [position_delta * (H_0 * grad_delta)^T +
                        (H_0 * grad_delta) * position_delta^T] +
                  rho * f * [position_delta * position_delta^T]
  ```

  All the terms in square brackets are matrices and are constructed using
  vector outer products. All the other terms on the right hand side are scalars.
  Also worth noting that the first and second lines are both rank 1 updates
  applied to the current inverse Hessian estimate.

  Args:
    grad_delta: `Tensor` of real dtype and same shape as `position_delta`.
      The difference between the gradient at the new position and the old
      position.
    position_delta: `Tensor` of real dtype and nonzero rank. The change in
      position from the previous iteration to the current one.
    inv_hessian_estimate: `Tensor` of real dtype and shape equal to
      the shape of `position_delta` concatenated with itself. If the shape of
      `position_delta` is [n1, n2,.., nr] then the shape of
      `inv_hessian_estimate` should be
      `[n1, n2, ..., nr, n1, n2, ..., nr]. The previous estimate of the
      inverse Hessian. Should be positive definite and symmetric.

  Returns:
    A tuple containing the following fields
    is_valid: Boolean `Tensor` indicating whether the update succeeded. The
      update can fail if the position change becomes orthogonal to the gradient
      change.
    next_inv_hessian_estimate: `Tensor` of same shape and dtype as
      `inv_hessian_estimate`. The next Hessian estimate updated using the
      BFGS update scheme. If the `inv_hessian_estimate` is symmetric and
      positive definite, the `next_inv_hessian_estimate` is guaranteed to
      satisfy the same conditions.
  """
  # The normalization term (y^T . s)
  normalization_factor = tf.reduce_sum(grad_delta * position_delta)

  is_singular = tf.equal(normalization_factor, 0)

  def _is_singular_fn():
    """If the update is singular, returns the old value."""
    return inv_hessian_estimate  # Return the old value

  def _do_update_fn():
    """Updates the Hessian estimate."""
    # The quadratic form: y^T.H.y.
    n = len(grad_delta.shape.as_list())
    # H.y where H is the inverse Hessian and y is the gradient change.
    # tensordot automatically iterates over the last n axes of the first tensor and
    # the first n axes of the second tensor. Passing in a scalar preserves shape information.
    conditioned_grad_delta = tf.tensordot(inv_hessian_estimate,
                                          grad_delta,
                                          n)
    conditioned_grad_delta_norm = tf.reduce_sum(
        conditioned_grad_delta * grad_delta)

    # The first rank 1 update term requires the outer product: s.y^T.
    # We leverage broadcasting to do this in a shape agnostic manner.
    # The position delta and the grad delta have the same rank, say, `n`. We
    # adjust the shape of the position delta by adding extra 'n' dimensions to
    # the right so its `padded` shape is original_shape + ([1] * n).
    cross_term = _tensor_product(position_delta, conditioned_grad_delta)
    # Symmetrize
    cross_term += _tensor_product(conditioned_grad_delta, position_delta)
    position_term = _tensor_product(position_delta, position_delta)
    with tf.control_dependencies([position_term]):
      position_term *= (1 + conditioned_grad_delta_norm / normalization_factor)

    next_inv_hessian_estimate = (
        inv_hessian_estimate +
        (position_term - cross_term) / normalization_factor)
    return next_inv_hessian_estimate

  next_estimate = smart_cond.smart_cond(is_singular,
                                        true_fn=_is_singular_fn,
                                        false_fn=_do_update_fn)

  return next_estimate


def _tensor_product(t1, t2):
  """Computes the tensor product of two tensors.

  If the rank of `t1` is `q` and the rank of `t2` is `r`, the result `z` is
  of rank `q+r` with shape `t1.shape + t2.shape`. The components of `z` are:

  ```None
    z[i1, i2, .., iq, j1, j2, .., jr] = t1[i1, .., iq] * t2[j1, .., jq]
  ```

  If both inputs are of rank 1, then the tensor product is equivalent to outer
  product of vectors.

  Note that tensor product is not commutative in general.

  Args:
    t1: A `tf.Tensor` of any dtype and non zero rank.
    t2: A `tf.Tensor` of same dtype as `t1` and non zero rank.

  Returns:
    product: A tensor with the same elements as the input `x` but with rank
      `r + n` where `r` is the rank of `x`.
  """
  t1_shape = tf.shape(t1)
  padding = tf.ones([tf.rank(t2)], dtype=t1_shape.dtype)
  padded_shape = tf.concat([t1_shape, padding], axis=0)
  t1_padded = tf.reshape(t1, padded_shape)
  return t1_padded * t2

