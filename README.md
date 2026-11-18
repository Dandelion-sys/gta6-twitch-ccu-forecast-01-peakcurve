# PeakCurve

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Dandelion-sys/gta6-twitch-ccu-forecast-01-peakcurve/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Dandelion-sys/gta6-twitch-ccu-forecast-01-peakcurve/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts GTA VI's launch-day Twitch viewers hour by hour (hours 2–24 UTC)
as 5/25/50/75/95% quantiles, for the make.fun bounty
`gta6-twitch-ccu-forecast-01`.

## Method

The forecast is anchored on the case's own hour-1 print and shaped by the
release-day curves of the biggest comparable launches in the case:

- **Reference pool:** usable comparables (hour-1 print present and
  positive) are ranked by hour-1 viewers and the top 15 form the pool.
  Big launches behave like other big launches.
- **Centre:** for each hour, the median across the pool of
  `ln(viewers[h] / viewers[1])`.
- **Spread:** the cross-comparable standard deviation of those log-ratios,
  scaled by 0.5, combined in quadrature with a `0.08 * sqrt(h - 1)` floor.
- **Quantiles:** `q = p1 * exp(median + z * sigma)` with
  `z = [-1.645, -0.674, 0, 0.674, 1.645]`.
- **Fallback:** with no usable comparables, the house persistence forecast
  (`q = p1 * exp(z * 0.15 * sqrt(h - 1))`) is used.

The constants were tuned by leave-one-out backtesting over the 37 usable
comparable release days in the practice cases. On the big launches (the
top 10 by hour-1, the population a mega-launch belongs to) the model
scores mean log pinball **0.202 vs 0.263 for the house baseline** (~23%
better), and its peak diagnostic is essentially unbiased: the median ratio
of forecast peak-hour q50 to actual peak is **0.99**, while the median over
all comparables over-shoots big launches' peaks by ~2x. The standard
deviation spread beat the IQR/1.349 spread in the same backtest
(0.202 vs 0.204).

As a plausibility check, the median ratio curve peaks at 1.25x hour 1, so
for a plausible hour-1 print around 2–2.5M the implied peak-hour q50 lands
near ~3M, in line with the ~2.75M betting-market line for the launch-day
Twitch peak. The ~3M figure is only an anchor for that sanity check —
nothing is clamped to it and the quantiles come entirely from the data.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` case in the input directory and writes one `<id>.out`
per case to the output directory. Python 3.13, standard library only, no
network. Deterministic and fast (well under a second per case).

## License

MIT — see [LICENSE](LICENSE).
