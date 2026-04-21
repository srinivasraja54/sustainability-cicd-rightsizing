"""Carbon-aware scheduling helper.

Queries Electricity Maps for current + forecast grid carbon intensity
in a given zone. Returns a deferral decision: should this workflow wait
for a greener window, and if so, when should it run?

Design principles:
  - Only deferrable workflows are candidates (schedule/cron, nightly
    batch). PR and push are time-sensitive — always run now.
  - If the carbon API is unreachable or the key is missing, run immediately.
    CI must never block on a third-party dependency.
  - Threshold and max-defer-window are env-tunable so a demo can force
    a deferral without waiting for a real bad-carbon day.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

ELECTRICITYMAPS_API = "https://api.electricitymap.org/v3"


@dataclass(frozen=True)
class DeferDecision:
    defer: bool
    current_gco2: float | None
    scheduled_for_utc: str | None
    scheduled_gco2: float | None
    reason: str


def _fetch_forecast(zone: str, api_key: str) -> list[dict] | None:
    resp = requests.get(
        f"{ELECTRICITYMAPS_API}/carbon-intensity/forecast",
        params={"zone": zone},
        headers={"auth-token": api_key},
        timeout=10,
    )
    if not resp.ok:
        return None
    return resp.json().get("forecast", [])


def decide(
    zone: str,
    *,
    threshold_gco2: float = 250.0,
    max_defer_hours: int = 8,
    api_key: str | None = None,
) -> DeferDecision:
    """Decide whether to defer based on the carbon forecast for `zone`.

    Returns `defer=False` on any error — CI never blocks on this.

    Demo hooks: set CARBON_MOCK=high to force a deferral, or CARBON_MOCK=low
    to force an immediate run. Useful for stage demos where the real forecast
    won't cooperate on cue.
    """
    mock = os.environ.get("CARBON_MOCK")
    if mock == "high":
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        return DeferDecision(
            True, 420.0, future, 140.0,
            "MOCK: current 420 gCO2/kWh → defer 2h to 140 gCO2/kWh window",
        )
    if mock == "low":
        return DeferDecision(
            False, 140.0, None, None,
            "MOCK: current 140 gCO2/kWh already green",
        )

    api_key = api_key or os.environ.get("ELECTRICITYMAPS_API_KEY")
    if not api_key:
        return DeferDecision(
            False, None, None, None, "no ELECTRICITYMAPS_API_KEY; running now"
        )

    try:
        forecast = _fetch_forecast(zone, api_key)
    except requests.RequestException as e:
        return DeferDecision(False, None, None, None, f"carbon API error: {e}")

    if not forecast:
        return DeferDecision(False, None, None, None, "no forecast data")

    now = datetime.now(timezone.utc)
    current = forecast[0]["carbonIntensity"]

    window = [
        f for f in forecast
        if 0 < (datetime.fromisoformat(f["datetime"]) - now).total_seconds() / 3600
             <= max_defer_hours
    ]
    if not window:
        return DeferDecision(False, current, None, None, "no forecast points in window")

    cleanest = min(window, key=lambda f: f["carbonIntensity"])

    if current <= threshold_gco2:
        return DeferDecision(
            False, current, None, None,
            f"current {current:.0f} gCO2/kWh already below threshold",
        )

    # Only defer if the greener window is meaningfully cleaner — >= 20% reduction.
    if cleanest["carbonIntensity"] >= current * 0.8:
        return DeferDecision(
            False, current, None, None,
            f"no >=20% greener window within {max_defer_hours}h",
        )

    return DeferDecision(
        defer=True,
        current_gco2=current,
        scheduled_for_utc=cleanest["datetime"],
        scheduled_gco2=cleanest["carbonIntensity"],
        reason=(
            f"current {current:.0f} gCO2/kWh → defer to {cleanest['datetime']} "
            f"at {cleanest['carbonIntensity']:.0f} gCO2/kWh"
        ),
    )
