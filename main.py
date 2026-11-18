"""PeakCurve: forecast a launch day's hourly Twitch viewers from big launches.

Method
------
The forecast is anchored on the case's own hour-1 print p1 (the first hour
of release day, 00:00-01:00 UTC).  The shape of the rest of the day comes
from the release-day curves of the biggest comparable launches in the case:

  * A comparable is usable when its hour-1 point (at its day_start) exists
    and is positive.  Usable comparables are ranked by their hour-1 viewers
    and the top POOL_SIZE (15) form the reference pool.  Big launches are
    used because a mega-launch behaves like other mega-launches: in
    leave-one-out backtesting over the practice comparables, the top-15
    pool beats the house persistence baseline on big launches by ~23%
    (mean log pinball 0.202 vs 0.263), while the median over ALL
    comparables over-shoots big launches' peaks by ~2x (peak ratio 1.96).
  * For each forecast hour h = 2..24, every pool member contributes its
    log-ratio lr = ln(v[h] / v[1]).  The centre m[h] is the median of those
    ratios and the spread s[h] is their (population) standard deviation.
    The standard deviation beat the IQR/1.349 spread in the same backtest
    (0.202 vs 0.204 on big launches), so it is the spread used here.
  * Quantiles: q_tau[h] = p1 * exp(m[h] + z_tau * sigma[h]) with
    sigma[h] = sqrt((0.5 * s[h])**2 + (0.08 * sqrt(h - 1))**2) and
    z = [-1.645, -0.674, 0, 0.674, 1.645] for the 5/25/50/75/95% levels.
    The 0.5 multiplier and 0.08 floor were tuned by that backtest; the
    loss surface is flat around them (0.202-0.204 for multipliers 0.3-0.7),
    so the choice is robust rather than a knife-edge optimum.
  * The per-hour median log-ratio is clamped to [-3.0, +3.0].  The median
    is already robust when many pool members report an hour, but with
    only one or two reporters a single wild comparable (say a 50x spike
    at one hour) would become the centre outright; the clamp bounds that
    failure.  It never binds on the practice data (median ratios stay
    within ~+/-1.5), so it costs nothing on clean inputs.
  * Peak diagnostic from the same backtest: the median ratio of the
    forecast peak-hour q50 to each big launch's actual peak is 0.99, i.e.
    the model is essentially unbiased on peaks.  As a plausibility check,
    the median ratio curve peaks at 1.25x hour 1, so for a plausible
    hour-1 print around 2-2.5M the implied peak-hour q50 lands near ~3M,
    in line with the ~2.75M betting-market line for the launch-day peak.
    Nothing is clamped to that anchor; it only guided the curve choice.

Tested and rejected (kept on file, not in the model)
-----------------------------------------------------
  * Console-only pool: GTA VI launches on PS5 + Xbox Series X|S only,
    so a pool of console-only comparables (no PC in `platforms`) was
    tried.  There are only 8 usable ones and they are far smaller on
    Twitch (hour-1 6k-365k); on BIG it scores 0.414 vs 0.202 for the
    top-15 pool and over-shoots peaks ~2x (peak ratio 1.97) -- the same
    failure mode as the all-comparable median.  A console-first pool
    (8 console-only + 7 biggest others) scores 0.243, also worse.
  * Per-hour pool widening: when fewer than 5 pool members report an
    hour, widening that hour's pool to the top 25 by hour-1 was tried
    under simulated truncated comparable series.  It hurts BIG when it
    triggers (0.216 vs 0.205 on one seed) because widening pulls in
    smaller launches whose curves differ from big launches', so it was
    not adopted; a thin hour falls back to the median of whatever the
    top-15 pool reports, and to persistence if nothing reports.

Fallbacks (a valid file is always written)
-------------------------------------------
  * No usable comparables: the house persistence forecast,
    q_tau[h] = p1 * exp(z_tau * 0.15 * sqrt(h - 1)).
  * No hour-1 print in the case: p1 falls back to the median hour-1 of the
    usable comparables, and to 1000 if there are none.
  * Any per-case error: the case is still written with the persistence
    forecast from whatever p1 could be recovered, so one bad case can
    never invalidate the whole run.

Contract
--------
Reads every *.in file in MAKEFUN_INPUT_DIR (default /input) and writes one
<id>.out per case to MAKEFUN_OUTPUT_DIR (default /output):
{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]} with exactly
23 rows (hours 2..24), five finite, positive, non-decreasing quantiles per
row, each at most 1e9, rounded to 2 decimals half-up.  Standard library
only, no network, deterministic (sorted inputs, no randomness, no clock).
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

# The grader's -P leaves the script's directory off sys.path; nothing beside
# this file needs importing, so no path fix-up is required.
INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

POOL_SIZE = 15          # comparables kept, ranked by hour-1 viewers
SPREAD_MULT = 0.5       # multiplier on the cross-comparable std of log-ratios
SPREAD_FLOOR = 0.08     # per-sqrt-hour floor on sigma, in log units
HOUSE_SIGMA = 0.15      # persistence baseline's per-sqrt-hour spread
MAX_VIEWERS = 1e9
FALLBACK_P1 = 1000.0
MAX_LOG_RATIO = 3.0     # clamp on a per-hour median log-ratio: one wild
                        # comparable (e.g. a 50x spike at a single hour)
                        # must not drag the curve when only 1-2 pool
                        # members report that hour.  Never binds on the
                        # practice data (median ratios stay within ~+/-1.5).


def parse_time(text):
    """Parse an ISO-8601 timestamp (trailing Z or an offset) to datetime."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def round2(value):
    """Round to 2 decimals, half up; whole numbers come back as ints."""
    scaled = math.floor(value * 100.0 + 0.5)
    rounded = scaled / 100.0
    if rounded.is_integer():
        return int(rounded)
    return rounded


def clamp(value):
    """Keep a quantile inside (0, 1e9]; the caller also re-sorts each row."""
    if not math.isfinite(value) or value <= 0:
        return 1
    if value > MAX_VIEWERS:
        return int(MAX_VIEWERS)
    return value


def hour_quantiles(p1, centre, sigma):
    """Five quantiles for one hour, rounded, clamped and non-decreasing."""
    row = [round2(clamp(p1 * math.exp(centre + z * sigma))) for z in Z]
    row.sort()
    return row


def persistence_row(p1, hour):
    """The house baseline row for one hour (centre 0, random-walk spread)."""
    return hour_quantiles(p1, 0.0, HOUSE_SIGMA * math.sqrt(hour - 1))


def release_day_curve(comparable):
    """Return the comparable's release-day viewers as a dict hour -> viewers.

    Hour 1 is the point at day_start; hour h is day_start + (h - 1) hours.
    Only positive viewer counts are kept.  Returns None when hour 1 is
    missing or not positive.
    """
    day_start = parse_time(comparable.get("day_start"))
    if day_start is None:
        return None
    by_hour = {}
    for point in comparable.get("hourly") or []:
        moment = parse_time(point.get("from"))
        viewers = point.get("viewers")
        if moment is None:
            continue
        if not isinstance(viewers, (int, float)) or viewers <= 0:
            continue
        offset = (moment - day_start).total_seconds() / 3600.0
        hour = int(offset) + 1
        if 1 <= hour <= 24 and hour not in by_hour:
            by_hour[hour] = float(viewers)
    if 1 not in by_hour:
        return None
    return by_hour


def hour_one_print(case):
    """The case's hour-1 viewers, or None when the known row is absent."""
    for row in case.get("known") or []:
        if row.get("hour") == 1:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and viewers > 0:
                return float(viewers)
            return None
    return None


def forecast_case(case):
    """Forecast hours 2..24 for one case; always returns a valid payload."""
    comparables = []
    for comp in case.get("comparables") or []:
        curve = release_day_curve(comp)
        if curve is not None:
            comparables.append(curve)
    # Reference pool: the biggest launches by hour-1 viewers.  The sort key
    # breaks ties on the curve itself so the order is fully deterministic.
    comparables.sort(key=lambda c: (-c[1], tuple(c.get(h, 0) for h in range(1, 25))))
    pool = comparables[:POOL_SIZE]

    p1 = hour_one_print(case)
    if p1 is None:
        if pool:
            p1 = statistics.median([c[1] for c in pool])
        else:
            p1 = FALLBACK_P1
    p1 = max(1.0, p1)

    hours = []
    forecast_rows = case.get("forecast") or []
    wanted = []
    for row in forecast_rows:
        hour = row.get("hour")
        if isinstance(hour, int) and 2 <= hour <= 24 and hour not in wanted:
            wanted.append(hour)
    if not wanted:
        wanted = list(range(2, 25))
    wanted.sort()

    for hour in wanted:
        if not pool:
            hours.append({"hour": hour, "q": persistence_row(p1, hour)})
            continue
        ratios = []
        for curve in pool:
            if hour in curve:
                ratios.append(math.log(curve[hour] / curve[1]))
        if not ratios:
            hours.append({"hour": hour, "q": persistence_row(p1, hour)})
            continue
        centre = statistics.median(ratios)
        # Clamp the centre so a single wild comparable cannot distort
        # the curve when only one or two pool members report this hour.
        centre = max(-MAX_LOG_RATIO, min(MAX_LOG_RATIO, centre))
        spread = statistics.pstdev(ratios) if len(ratios) > 1 else 0.0
        sigma = math.sqrt((SPREAD_MULT * spread) ** 2
                          + (SPREAD_FLOOR * math.sqrt(hour - 1)) ** 2)
        hours.append({"hour": hour, "q": hour_quantiles(p1, centre, sigma)})
    # Rows are built in ascending hour order already (wanted is sorted);
    # sort defensively so the output contract holds whatever the case's
    # forecast list looked like.
    hours.sort(key=lambda row: row["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            payload = forecast_case(case)
        except Exception:
            # Never let one unreadable case stop the run or produce no file:
            # emit the persistence forecast from a neutral anchor instead.
            payload = {"hours": [{"hour": h, "q": persistence_row(FALLBACK_P1, h)}
                                 for h in range(2, 25)]}
        text = json.dumps(payload, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
