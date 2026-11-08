"""
# UMAP of the Kelmarsh turbine operating distributions

Embeds a random sample of 10-minute SCADA records (all six turbines, 2016-2024) into two
dimensions with UMAP and draws ONE plot with every turbine on it, plus how dispersed each
turbine's records are: the mean distance to the turbine's own centroid over the standardised
signals, and the share of the plot covered by the densest 50% and 90% of its records.

The Kelmarsh v4 `Turbine_Data_*.csv` files for 2023 and 2024 are ~2.9 GB each because they
repeat the whole year ~40 times as padding rows (2,174,760 rows for 52,560 distinct 10-minute
timestamps) that hold NaN everywhere except a few constant columns. Rows without wind speed
or power are therefore dropped while reading.

Needs: numpy, pandas, scipy, scikit-learn, umap-learn, matplotlib (not project dependencies).

    python -I scripts/umap_turbines.py --data-dir dataset/kelmarsh_v4/extracted \
        --out dataset/kelmarsh_v4/umap_turbines.png

The following can be imported from this module:
- `main`
"""

import argparse
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as patheffects  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

__all__ = ["main"]

FILE_RE = re.compile(r"Turbine_Data_Kelmarsh_(\d)_")
# Per-interval summaries of a signal, left out so each physical signal counts once, and
# cumulative counters, which encode the turbine's history rather than its operating state.
DROPPED_FRAGMENTS = (", Standard deviation", ", Minimum", ", Maximum", "Long Term", "counter")
REQUIRED = ["Wind speed (m/s)", "Power (kW)"]
MAX_NAN_COLUMN = 0.20
MAX_NAN_ROW = 0.30
CHUNK_ROWS = 250_000
TIME_COL = "Date and time"
GRID_BINS = 240
CORE_SHARES = (0.5, 0.9)

# Turbine colours: the Okabe-Ito set. The default reference palette cannot hold six series in a
# scatter (every six-colour subset fails the all-pairs gates), this one passes them: worst
# normal-vision pair 15.6 (floor 15), worst colour-blind pair 7.6, which is in the warning band
# and is why the legend table repeats every number. Checked with the dataviz validator.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e3e2de"
SERIES = {1: "#0072B2", 2: "#D55E00", 3: "#009E73", 4: "#E69F00", 5: "#56B4E9", 6: "#CC79A7"}


def read_header(path):
    """
    Read the column names and the number of leading comment lines of a Greenbyte csv.

    :param path: Path of a `Turbine_Data_*.csv` file.

    :returns: Tuple of (column names, number of header lines before the first data row).
    """
    with open(path, encoding="utf-8-sig") as handle:
        for n_header, line in enumerate(handle):
            if not line.startswith("#"):
                break
    names = pd.read_csv(path, skiprows=n_header - 1, nrows=0).columns.tolist()
    names[0] = TIME_COL
    return names, n_header


def load_file(job):
    """
    Read one turbine-year file, drop padding rows and keep a random sample.

    :param job: Tuple of (path, feature names, sampling fraction, seed).

    :returns: DataFrame with the features plus `turbine`, `time`.
    """
    path, features, fraction, seed = job
    names, n_header = read_header(path)
    rng = np.random.default_rng(seed)
    parts = []
    reader = pd.read_csv(
        path,
        skiprows=n_header,
        header=None,
        names=names,
        usecols=[TIME_COL, *features],
        dtype={name: "float32" for name in features},
        chunksize=CHUNK_ROWS,
    )
    for chunk in reader:
        # Padding rows still carry a few constant columns, so "all NaN" is not enough: a real
        # record always has wind speed and power.
        chunk = chunk.dropna(subset=REQUIRED, how="any")
        keep = rng.random(len(chunk)) < fraction
        parts.append(chunk[keep])
    frame = pd.concat(parts, ignore_index=True).copy()
    frame["turbine"] = int(FILE_RE.search(path.name).group(1))
    frame["time"] = pd.to_datetime(frame.pop(TIME_COL))
    return frame


def common_features(files):
    """
    Find the signals present in every file, minus the summary variants and counters.

    :param files: Paths of all `Turbine_Data_*.csv` files.

    :returns: Sorted list of column names.
    """
    shared = None
    for path in files:
        names = set(read_header(path)[0][1:])
        shared = names if shared is None else shared & names
    return sorted(n for n in shared if not any(frag in n for frag in DROPPED_FRAGMENTS))


def build_matrix(frame, features):
    """
    Drop sparse columns and rows, impute the rest with the median and standardise.

    :param frame: Sampled records with the candidate features.
    :param features: Candidate feature names.

    :returns: Tuple of (filtered frame, scaled matrix, kept feature names).
    """
    nan_rate = frame[features].isna().mean()
    kept = nan_rate[nan_rate <= MAX_NAN_COLUMN].index.tolist()
    frame = frame[frame[kept].isna().mean(axis=1) <= MAX_NAN_ROW].reset_index(drop=True)
    values = frame[kept].fillna(frame[kept].median())
    spread = values.std()
    kept = spread[spread > 0].index.tolist()
    scaled = StandardScaler().fit_transform(values[kept])
    return frame, np.clip(scaled, -5, 5), kept


def dispersion(matrix, embedding, turbines):
    """
    Measure how spread out each turbine's records are.

    Three views of the same question, for each turbine and for all records together. In the
    full standardised space: the mean distance of a record to its group's centroid. In the
    plane: the same distance, and the share of the plot's bounding box covered by the densest
    50% / 90% of the group's records (shared grid, so the shares are comparable).

    :param matrix: Standardised features, shape (n, d).
    :param embedding: UMAP coordinates, shape (n, 2).
    :param turbines: Turbine number of every row.

    :returns: Tuple of (DataFrame with one row per turbine plus an "All" row, density grids and
        level thresholds per row, (x centres, y centres), ratio of mean centroid separation
        between turbines to their mean within-turbine spread).
    """
    pad = 0.5
    x_edges = np.linspace(embedding[:, 0].min() - pad, embedding[:, 0].max() + pad, GRID_BINS + 1)
    y_edges = np.linspace(embedding[:, 1].min() - pad, embedding[:, 1].max() + pad, GRID_BINS + 1)
    centres = ((x_edges[:-1] + x_edges[1:]) / 2, (y_edges[:-1] + y_edges[1:]) / 2)
    groups = [("All", np.ones(len(turbines), dtype=bool))]
    groups += [(int(t), turbines == t) for t in sorted(set(turbines))]
    rows, grids, centroids = [], {}, {}
    for label, mine in groups:
        centroid = matrix[mine].mean(axis=0)
        if label != "All":
            centroids[label] = centroid
        plane = embedding[mine]
        counts, _, _ = np.histogram2d(plane[:, 0], plane[:, 1], bins=[x_edges, y_edges])
        density = gaussian_filter(counts, sigma=2)
        ordered = np.sort(density.ravel())[::-1]
        cumulative = np.cumsum(ordered) / ordered.sum()
        row = {
            "turbine": label,
            "records": int(mine.sum()),
            "spread_features": float(np.linalg.norm(matrix[mine] - centroid, axis=1).mean()),
            "spread_plane": float(np.linalg.norm(plane - plane.mean(axis=0), axis=1).mean()),
        }
        thresholds = []
        for share in CORE_SHARES:
            level = ordered[min(np.searchsorted(cumulative, share), len(ordered) - 1)]
            thresholds.append(level)
            row[f"area_{int(share * 100)}_pct"] = float((density >= level).mean() * 100)
        grids[label] = (density, thresholds)
        rows.append(row)
    table = pd.DataFrame(rows)
    per_turbine = table[table["turbine"] != "All"]
    gaps = [np.linalg.norm(centroids[a] - centroids[b]) for a, b in combinations(centroids, 2)]
    return table, grids, centres, float(np.mean(gaps) / per_turbine["spread_features"].mean())


def plot(frame, embedding, table, grids, centres, out_path):
    """
    Draw the single plot: every record coloured by turbine, with the contours of the whole cloud.

    :param frame: Filtered records with `turbine` and `time`.
    :param embedding: Array of shape (n, 2).
    :param table: Output of `dispersion`.
    :param grids: Per-group density grids and level thresholds from `dispersion`.
    :param centres: Grid cell centres from `dispersion`.
    :param out_path: Where to write the PNG.

    :returns: None.
    """
    fig, ax = plt.subplots(figsize=(15, 8.6), facecolor=SURFACE)
    fig.subplots_adjust(left=0.025, right=0.74, top=0.89, bottom=0.11)
    ax.set_facecolor(SURFACE)
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_color(GRID)

    order = np.random.default_rng(0).permutation(len(frame))
    colours = frame["turbine"].map(SERIES).to_numpy()
    ax.scatter(
        embedding[order, 0],
        embedding[order, 1],
        c=colours[order],
        s=1.8,
        alpha=0.7,
        linewidths=0,
        rasterized=True,
    )

    density, thresholds = grids["All"]
    contours = ax.contour(
        centres[0],
        centres[1],
        density.T,
        levels=sorted(thresholds),
        colors=INK,
        linewidths=[0.9, 1.6],
        linestyles=["dashed", "solid"],
    )
    contours.set_path_effects([patheffects.withStroke(linewidth=3, foreground=SURFACE)])

    handles, labels = [], []
    for _, row in table.iterrows():
        if row["turbine"] == "All":
            handles.append(Line2D([0], [0], color=INK, lw=1.6))
            name = "All"
        else:
            turbine = int(row["turbine"])
            handles.append(
                Line2D([0], [0], marker="o", color=SURFACE, markerfacecolor=SERIES[turbine],
                       markersize=9, lw=0)
            )
            name = f"T{turbine}"
        labels.append(
            f"{name:<4}{row['spread_features']:>7.2f}{row['spread_plane']:>8.2f}"
            f"{row['area_50_pct']:>7.1f}%{row['area_90_pct']:>6.1f}%"
        )
    legend = ax.legend(
        handles,
        labels,
        title=f"{'':<4}{'spread':>7}{'spread':>8}{'core':>8}{'core':>7}\n"
        f"{'':<4}{'115-D':>7}{'plane':>8}{'50%':>8}{'90%':>7}",
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0,
        frameon=True,
        facecolor=SURFACE,
        edgecolor=GRID,
        prop={"family": "monospace", "size": 10.5},
        title_fontproperties={"family": "monospace", "size": 10},
        handlelength=1.6,
        borderpad=1.0,
        labelspacing=0.8,
        labelcolor=INK,
    )
    legend.get_title().set_color(INK_SECONDARY)
    legend.get_title().set_ha("left")

    years = frame["time"].dt.year
    fig.text(
        0.025,
        0.945,
        f"Kelmarsh wind farm: UMAP of {len(frame):,} sampled 10-minute SCADA records, "
        f"{years.min()}-{years.max()}",
        fontsize=14,
        color=INK,
    )
    fig.text(
        0.025,
        0.91,
        "Each dot is one record, coloured by turbine. Black contours enclose the densest 50% "
        "(solid) and 90% (dashed) of all records.",
        fontsize=9.5,
        color=INK_SECONDARY,
    )
    fig.text(
        0.752,
        0.6,
        "spread 115-D: mean distance to the turbine's\n"
        "  centroid, 115 standardised signals\n"
        "spread plane: same, on the two UMAP axes\n"
        "core 50% / 90%: share of the plot's area\n"
        "  holding the densest 50% / 90% of records",
        fontsize=8.5,
        color=INK_SECONDARY,
        family="monospace",
        va="top",
    )
    fig.text(
        0.025,
        0.045,
        "UMAP axes carry no unit; only neighbourhoods matter. Points are drawn in random order, "
        "so where one colour dominates a region, that turbine really dominates it.",
        fontsize=8.5,
        color=INK_SECONDARY,
    )
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main(argv=None):
    """
    Load, sample, embed, measure dispersion and plot.

    :param argv: Command line arguments. Defaults to None, meaning `sys.argv[1:]`.

    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].lstrip("# \n"))
    parser.add_argument("--data-dir", type=Path, required=True, help="folder with Kelmarsh_SCADA_*")
    parser.add_argument("--out", type=Path, required=True, help="output PNG")
    parser.add_argument("--per-turbine", type=int, default=15_000, help="records kept per turbine")
    parser.add_argument("--neighbors", type=int, default=30)
    parser.add_argument("--min-dist", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args(argv)

    import umap  # heavy and only needed here

    files = sorted(args.data_dir.glob("Kelmarsh_SCADA_*/Turbine_Data_*.csv"))
    if not files:
        print(f"no Turbine_Data csv under {args.data_dir}", file=sys.stderr)
        return 1
    features = common_features(files)
    missing = [name for name in REQUIRED if name not in features]
    if missing:
        print(f"required signals not shared by all files: {missing}", file=sys.stderr)
        return 1
    print(f"{len(files)} files, {len(features)} signals shared by all of them", flush=True)

    years = len({path.parent.name for path in files})
    fraction = args.per_turbine / (years * 52_560)
    jobs = [(path, features, fraction, args.seed + i) for i, path in enumerate(files)]
    start = time.time()
    with ProcessPoolExecutor(args.workers) as pool:
        frames = list(pool.map(load_file, jobs))
    frame = pd.concat(frames, ignore_index=True)
    print(f"read {len(frame):,} sampled rows in {time.time() - start:.0f}s", flush=True)

    frame, matrix, kept = build_matrix(frame, features)
    print(f"{len(frame):,} rows x {len(kept)} features after filtering", flush=True)

    start = time.time()
    reducer = umap.UMAP(n_neighbors=args.neighbors, min_dist=args.min_dist, random_state=args.seed)
    embedding = reducer.fit_transform(matrix)
    print(f"umap done in {time.time() - start:.0f}s", flush=True)

    table, grids, centres, separation = dispersion(matrix, embedding, frame["turbine"].to_numpy())
    print(table.round(2).to_string(index=False), flush=True)
    print(
        f"centroid separation / within-turbine spread = {separation:.3f} "
        "(0 = identical centres, 1 = centres as far apart as a record is from its own)",
        flush=True,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    plot(frame, embedding, table, grids, centres, args.out)
    table.to_csv(args.out.with_name(args.out.stem + "_dispersion.csv"), index=False)
    out = frame[["turbine", "time", *REQUIRED]].copy()
    out["umap_1"], out["umap_2"] = embedding[:, 0], embedding[:, 1]
    out.to_csv(args.out.with_suffix(".csv"), index=False)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
