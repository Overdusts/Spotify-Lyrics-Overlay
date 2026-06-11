"""Closed-form damped harmonic oscillator (AMLL-style spring).

Solves ``m*x'' + c*x' + k*x = 0`` *exactly* for the displacement
``x = value - target``, selecting the analytic under-, critically- or
over-damped branch each step. Because every step evaluates the exact
solution of the ODE (rather than Euler-integrating it), the spring is
unconditionally stable for any time step; ``dt`` is additionally clamped to
50 ms so a long event-loop stall advances the animation at most that far.

Arrival contract: when both ``|value - target| < 0.01`` and
``|velocity| < 0.01`` the spring snaps exactly onto the target and reports
``settled`` — the render loop uses this to stop scheduling frames.
"""

from __future__ import annotations

import logging
import math

log = logging.getLogger(__name__)

#: Maximum simulated step per :meth:`Spring.update` call, seconds.
MAX_DT = 0.05

#: Arrival threshold for both displacement and velocity.
SETTLE_EPSILON = 0.01

#: Damping ratios within this band of 1.0 use the critically-damped branch
#: (the under/over-damped formulas degenerate numerically as zeta -> 1).
_CRITICAL_BAND = 1e-6


class Spring:
    """One-dimensional spring animating ``value`` toward ``target``."""

    __slots__ = ("_mass", "_damping", "_stiffness", "_value", "_target", "_velocity")

    def __init__(self, mass: float, damping: float, stiffness: float, value: float = 0.0) -> None:
        self._check_params(mass, damping, stiffness)
        self._mass = float(mass)
        self._damping = float(damping)
        self._stiffness = float(stiffness)
        self._value = float(value)
        self._target = float(value)
        self._velocity = 0.0

    @staticmethod
    def _check_params(mass: float, damping: float, stiffness: float) -> None:
        if mass <= 0.0:
            raise ValueError(f"spring mass must be > 0, got {mass!r}")
        if stiffness <= 0.0:
            raise ValueError(f"spring stiffness must be > 0, got {stiffness!r}")
        if damping < 0.0:
            raise ValueError(f"spring damping must be >= 0, got {damping!r}")

    def set_params(self, mass: float, damping: float, stiffness: float) -> None:
        """Retune the oscillator mid-flight; value/velocity/target persist.

        Used e.g. for the tempo-adaptive line stiffness (SPEC §3.3).
        """
        self._check_params(mass, damping, stiffness)
        self._mass = float(mass)
        self._damping = float(damping)
        self._stiffness = float(stiffness)

    def set_target(self, target: float) -> None:
        """Aim at a new target; current value and velocity carry over."""
        self._target = float(target)

    def snap(self, value: float) -> None:
        """Teleport: value = target = ``value``, velocity zeroed (settled)."""
        v = float(value)
        self._value = v
        self._target = v
        self._velocity = 0.0

    @property
    def value(self) -> float:
        return self._value

    @property
    def target(self) -> float:
        return self._target

    @property
    def velocity(self) -> float:
        return self._velocity

    @property
    def settled(self) -> bool:
        return (
            abs(self._value - self._target) < SETTLE_EPSILON
            and abs(self._velocity) < SETTLE_EPSILON
        )

    def update(self, dt: float) -> float:
        """Advance the closed-form solution by ``dt`` seconds; return value.

        ``dt`` is clamped to ``MAX_DT`` internally; non-positive ``dt`` is a
        no-op. On arrival (per :attr:`settled` thresholds) the spring snaps
        exactly onto the target so downstream consumers see clean rest values.
        """
        if dt <= 0.0:
            return self._value
        dt = min(float(dt), MAX_DT)

        if self.settled:
            # Already within the arrival window: finish the snap and sleep.
            self._value = self._target
            self._velocity = 0.0
            return self._value

        x0 = self._value - self._target
        v0 = self._velocity
        omega0 = math.sqrt(self._stiffness / self._mass)
        zeta = self._damping / (2.0 * math.sqrt(self._stiffness * self._mass))

        if abs(zeta - 1.0) < _CRITICAL_BAND:
            # Critically damped: x(t) = (x0 + (v0 + w0*x0) t) e^(-w0 t)
            b = v0 + omega0 * x0
            decay = math.exp(-omega0 * dt)
            x = (x0 + b * dt) * decay
            v = (v0 - omega0 * b * dt) * decay
        elif zeta < 1.0:
            # Under-damped: decaying sinusoid at damped frequency wd.
            sigma = zeta * omega0
            omega_d = omega0 * math.sqrt(1.0 - zeta * zeta)
            b = (v0 + sigma * x0) / omega_d
            decay = math.exp(-sigma * dt)
            cos_wd = math.cos(omega_d * dt)
            sin_wd = math.sin(omega_d * dt)
            x = decay * (x0 * cos_wd + b * sin_wd)
            v = decay * (v0 * cos_wd - (x0 * omega_d + sigma * b) * sin_wd)
        else:
            # Over-damped: sum of two decaying exponentials.
            disc = math.sqrt(zeta * zeta - 1.0)
            r1 = -omega0 * (zeta - disc)
            r2 = -omega0 * (zeta + disc)
            c1 = (v0 - r2 * x0) / (r1 - r2)
            c2 = x0 - c1
            e1 = math.exp(r1 * dt)
            e2 = math.exp(r2 * dt)
            x = c1 * e1 + c2 * e2
            v = c1 * r1 * e1 + c2 * r2 * e2

        if abs(x) < SETTLE_EPSILON and abs(v) < SETTLE_EPSILON:
            self._value = self._target
            self._velocity = 0.0
        else:
            self._value = self._target + x
            self._velocity = v
        return self._value
