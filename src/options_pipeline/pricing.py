"""Black-Scholes pricing, Greeks, and implied-volatility inversion."""

from __future__ import annotations

import math


SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _d1_d2(spot: float, strike: float, rate: float, vol: float, tau: float, dividend_yield: float = 0.0) -> tuple[float, float]:
    vol_sqrt_t = max(vol, 1e-8) * math.sqrt(max(tau, 1e-8))
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * vol * vol) * tau) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def black_scholes_price(
    spot: float,
    strike: float,
    rate: float,
    vol: float,
    tau: float,
    option_type: str,
    *,
    dividend_yield: float = 0.0,
) -> float:
    """Return the European option price under Black-Scholes assumptions."""

    if tau <= 0:
        return max(spot - strike, 0.0) if option_type.upper() == "C" else max(strike - spot, 0.0)
    d1, d2 = _d1_d2(spot, strike, rate, vol, tau, dividend_yield)
    disc_q = math.exp(-dividend_yield * tau)
    disc_r = math.exp(-rate * tau)
    if option_type.upper() == "C":
        return spot * disc_q * _norm_cdf(d1) - strike * disc_r * _norm_cdf(d2)
    if option_type.upper() == "P":
        return strike * disc_r * _norm_cdf(-d2) - spot * disc_q * _norm_cdf(-d1)
    raise ValueError("option_type must be C or P")


def greeks(
    spot: float,
    strike: float,
    rate: float,
    vol: float,
    tau: float,
    option_type: str,
    *,
    dividend_yield: float = 0.0,
) -> dict[str, float]:
    """Return delta, gamma, vega, theta, vanna proxy, and charm proxy."""

    d1, d2 = _d1_d2(spot, strike, rate, vol, max(tau, 1e-8), dividend_yield)
    disc_q = math.exp(-dividend_yield * tau)
    disc_r = math.exp(-rate * tau)
    pdf = _norm_pdf(d1)
    call_delta = disc_q * _norm_cdf(d1)
    delta = call_delta if option_type.upper() == "C" else call_delta - disc_q
    gamma = disc_q * pdf / (spot * max(vol, 1e-8) * math.sqrt(max(tau, 1e-8)))
    vega = spot * disc_q * pdf * math.sqrt(max(tau, 1e-8)) / 100.0
    if option_type.upper() == "C":
        theta = (
            -(spot * disc_q * pdf * vol) / (2.0 * math.sqrt(max(tau, 1e-8)))
            - rate * strike * disc_r * _norm_cdf(d2)
            + dividend_yield * spot * disc_q * _norm_cdf(d1)
        ) / 365.0
    else:
        theta = (
            -(spot * disc_q * pdf * vol) / (2.0 * math.sqrt(max(tau, 1e-8)))
            + rate * strike * disc_r * _norm_cdf(-d2)
            - dividend_yield * spot * disc_q * _norm_cdf(-d1)
        ) / 365.0
    vanna_proxy = -disc_q * pdf * d2 / max(vol, 1e-8)
    charm_proxy = -delta / max(tau * 252.0, 1.0)
    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "vega": float(vega),
        "theta": float(theta),
        "vanna_proxy": float(vanna_proxy),
        "charm_proxy": float(charm_proxy),
    }


def implied_volatility(
    price: float,
    spot: float,
    strike: float,
    rate: float,
    tau: float,
    option_type: str,
    *,
    low: float = 0.0001,
    high: float = 5.0,
    tolerance: float = 1e-5,
    max_iter: int = 100,
) -> float:
    """Invert Black-Scholes price with a robust bisection search."""

    intrinsic = max(spot - strike, 0.0) if option_type.upper() == "C" else max(strike - spot, 0.0)
    if price <= intrinsic + 1e-10:
        return low
    lo, hi = low, high
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        model = black_scholes_price(spot, strike, rate, mid, tau, option_type)
        if abs(model - price) < tolerance:
            return float(mid)
        if model > price:
            hi = mid
        else:
            lo = mid
    return float((lo + hi) / 2.0)

