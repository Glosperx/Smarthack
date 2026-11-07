# Hill wind site finder

Where in Romania's hills (200-800 m) will a wind park catch the most wind over the next two
full years? The site finder answers with a heatmap of forecast mean wind at 100 m hub
height, a ranked list of candidate park sites, and a click-anywhere point forecast.

```bash
make resource                 # first run downloads ~300 MB (cached), then about a minute
make resource ARGS=--no-names # skip the OpenStreetMap locality lookup (offline rebuild)
```

The build writes `models/resource/` (`summary.json`, `sites.json`, `heatmap.png`,
`atlas_grid.npz`), served by `GET /api/resource/{summary,sites,heatmap.png,point}` and
shown by the **Site finder** panel on the map.

## Why not just "predict the wind in two years"?

Nobody can forecast weather two years ahead. What *can* be estimated is the wind
**climate** of those years: the mean, and how far it may swing. So the question splits in
two, each answered by the data that is good at it:

| Question | Data | Resolution |
|---|---|---|
| **Where** is it windy? Ridges, exposed plateaus, valley shelter | Global Wind Atlas v3 mean wind at 100 m (2008-2017) | 250 m |
| **How much** will the mean move in the forecast years? | NASA POWER (MERRA-2) monthly wind at 50 m, 1981-last year | ~50 km |
| **Is it a hill, can we build there?** | Copernicus DEM GLO-90 elevation and slope | 90 m |

Forecast wind = Global Wind Atlas wind x (forecast mean / 2008-2017 mean of the NASA cell),
the factor interpolated bilinearly between NASA cells. The ratio cancels the height
difference between the two datasets and keeps the 250 m terrain detail.

## Choosing the forecast method: a rolling-origin backtest

For every year *t* from 1990, each method sees only data up to *t* and forecasts the mean
of years *t+2* and *t+3* (from data ending 2025, that is 2027-2028), for every NASA cell.

| Method | What it assumes |
|---|---|
| Persistence | next years look like the last one |
| Mean of all years / last 10 / last 5 | the climate is stable / drifts slowly / drifts fast |
| Exponentially weighted mean (half-life 8 y) | recent years count more, smoothly |
| 15-year linear trend | the drift continues |
| Learned blend | ridge regression over the above, refitted at each origin on past origins only |

The method is **selected on the validation years** (targets 2004-2015) and **reported on
held-out test years** (targets 2016-2025) it never influenced. The P10-P90 band is the
10th-90th percentile of the selected method's relative errors before the test period; its
coverage on the test years checks it is honest.

Results are printed by `make resource` and shown in the panel under *How is this forecast
made?*. The build of 2026-11-07 (data 1981-2025, forecast 2027-2028, 187 NASA cells):

| Method | Validation MAE | Test MAE (m/s) | Test error |
|---|---|---|---|
| **Mean of last 5 years (selected)** | **0.111** | **0.109** | **2.1 %** |
| Exponentially weighted mean | 0.116 | 0.096 | 1.9 % |
| Mean of last 10 years | 0.118 | 0.102 | 2.0 % |
| Mean of all years | 0.122 | 0.099 | 2.0 % |
| Learned blend (ridge) | 0.127 | 0.095 | 1.9 % |
| 15-year linear trend | 0.136 | 0.135 | 2.7 % |
| Persistence (last year) | 0.153 | 0.162 | 3.2 % |

P10-P90 band -3.8 % / +3.2 %, which held on 78 % of test outcomes (nominal 80 %). Ranking
of areas, forecast vs actual: Spearman 0.994. Hill terrain 200-800 m: 100,912 km2, of which
65,542 km2 with slope at most 10 deg.

The method chosen on validation is not the best on the test years (the exponentially
weighted mean and the blend are, by ~0.01 m/s): the differences between climatology-type
methods are within noise, and the selection rule is kept honest rather than re-picked
after seeing the test. In short: persistence and trend extrapolation are the worst (interannual
wind is mostly chaotic), climatology-type means are best, the learned blend does not beat
them by a meaningful margin, the error is about **2 %** (~0.1 m/s) and the ranking of areas
is almost perfectly stable (Spearman ~0.99). That stability is the useful finding: *where*
the best wind is does not change in two years; *how much* moves by a few percent, with a
calibrated band.

## Candidate sites

Eligible cells: inside Romania, elevation 200-800 m, mean slope at most 10 deg (roads and
crane pads). Each cell is scored by the mean forecast wind of a ~3.5 x 3.5 km window
(a park footprint) with at least 60 % eligible terrain; the best window is taken, everything
within 20 km is removed, and so on, for 15 sites spread over different regions. Names come
from OpenStreetMap Nominatim.

## Limits

- Not yet excluded: Natura 2000 and other protected areas, settlements and their setback
  distances, distance to the 110 kV grid, existing parks. These are the next layers.
- Mean wind is not energy: production depends on the wind's distribution and the turbine's
  power curve. The ranking is the same to first order; a capacity factor layer is next.
- The Global Wind Atlas is itself a model (ERA5 downscaled with WAsP), validated on masts
  but not on every Romanian ridge. A measurement campaign (LiDAR or mast) is the step after
  this screening, and the screening tells where to put it.

## Data sources and licences

| Dataset | Licence |
|---|---|
| [NASA POWER](https://power.larc.nasa.gov/) (MERRA-2) | NASA open data |
| [Global Wind Atlas](https://globalwindatlas.info/) v3 | CC BY 4.0, DTU / World Bank Group |
| [Copernicus DEM GLO-90](https://registry.opendata.aws/copernicus-dem/) | Copernicus DEM licence, free with attribution |
| [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/) | ODbL, (c) OpenStreetMap contributors |
