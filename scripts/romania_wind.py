"""
# Romania wind: every hour of the last ten years, downscaled to 250 m, filtered to 200-800 m

Downloads every source the map needs, in parallel, keeps all of it, then filters by terrain
elevation:

- ERA5 hourly reanalysis (Copernicus CDS), from 2016 to the last complete month the CDS catalogue
  lists: wind u/v at 100 m and at 10 m, every hour, over Romania on a 0.25 degree grid (~25 km).
  Newest month first, strictly one request at a time: since October 2026 ECMWF suspends accounts
  that submit requests in parallel or in large batches, or keep submitting invalid ones (such as a
  month not published yet). `--months-per-request` sets the size, up to half a year of four
  variables, the most one request may hold under the CDS size limit; smaller requests may leave the
  CDS queue sooner. Files of different sizes mix, so the size can change between runs.
- Global Wind Atlas 3 (GWA): 250 m long-term mean wind speed at hub height. An ERA5 cell is too
  coarse to filter by elevation (one cell spans valleys and ridges), so each day's ERA5 field, as a
  ratio to its own ten-year mean, is interpolated onto the GWA grid and multiplied by the GWA mean:
  the day-to-day variation comes from ERA5, the spatial detail from GWA.
- Copernicus DEM GLO-90 (AWS open data, no account): terrain elevation, averaged onto the GWA grid.
  Only pixels between 200 and 800 m above sea level are kept; the Black Sea (0 m) is dropped.

What `build` writes under `<data-dir>/`:

- `era5/daily_<years>.nc`: daily mean speed at 100 m and 10 m on the ERA5 grid, all of Romania.
- `out/daily_250m/wind<height>_daily_<year>.nc`: daily mean speed at hub height on the 250 m grid,
  200-800 m pixels only (int16 in 0.01 m/s, compressed), one file per year, several years at once.
- `out/daily_band_mean_<tag>.csv`: one row per day, the mean over the 200-800 m pixels.
- GeoTIFFs and PNG heatmaps: the typical-year mean, P10/P90 of the yearly means, month by month.

A given day two years ahead cannot be predicted; the typical year, and its spread, can.

ERA5 needs a free account at https://cds.climate.copernicus.eu, its token in `~/.cdsapirc`
(`url: https://cds.climate.copernicus.eu/api` and `key: <token>`), and the licence of "ERA5 hourly
data on single levels" accepted once on the dataset's page. Without them ERA5 is skipped and the map
is the GWA mean alone.

Needs: numpy, rasterio, xarray, netCDF4, matplotlib, cdsapi (not project dependencies).

    uv run --no-project --with numpy --with rasterio --with xarray --with netCDF4 \
        --with matplotlib --with cdsapi python -I scripts/romania_wind.py all

Both steps print a status line every few seconds with what is done and an ETA. Both resume: a file
already on disk is not fetched or written again.

The following can be imported from this module:
- `main`
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.request
import zipfile

__all__ = ["main"]

DEFAULT_DATA_DIR = Path("dataset/romania_wind")
GWA_URL = "https://globalwindatlas.info/api/gis/country/ROU/wind-speed/{height}"
GWA_HEIGHTS = (10, 50, 100, 150, 200)
DEM_URL = "https://copernicus-dem-90m.s3.amazonaws.com/{name}/{name}.tif"
DEM_LATS = range(43, 49)  # 1x1 degree tiles named by their south-west corner
DEM_LONS = range(20, 30)
DEM_WORKERS = 16  # S3 has no queue: here parallel downloads do pay off
ERA5_DATASET = "reanalysis-era5-single-levels"
ERA5_VARIABLES = [
    "100m_u_component_of_wind",
    "100m_v_component_of_wind",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
]
ERA5_AREA = [49.0, 19.5, 43.0, 30.5]  # N, W, S, E: Romania plus a margin for interpolation
ERA5_TYPICAL = "the ETA appears once the first request is done"
MONTHS_PER_REQUEST = 6  # half a year of four variables: 104,832 of the CDS limit of 121,000 units
ERA5_FILE = re.compile(r"era5_(\d{4})_(\d{2})-(\d{2})\.nc")
CDS_PAUSE_S = 10  # between requests, which ECMWF asks to be sequential
USER_AGENT = "romania-wind-heatmap/1.0"
RETRIES = 3

#: The CDS request states, as the client reports them, and how the status line names them.
CDS_STATES = {"accepted": "queued", "running": "running", "successful": "downloading"}

#: Sequential one-hue ramp, light (low wind) to dark (high wind).
RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5"]
RAMP += ["#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
OUT_OF_BAND = "#dcdbd7"
INK = "#2b2b29"
MUTED = "#6b6a66"
MONTHS_RO = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "nov", "dec"]

#: What each process writing daily files shares: set once per process by `_init_worker`.
_WORKER: dict[str, Any] = {}


def fmt_duration(seconds: float) -> str:
    """
    Format a duration as `m:ss`, or `h:mm:ss` past an hour.

    :param seconds: The duration in seconds.

    :returns text: The formatted duration.
    """
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class Job:
    """Progress of one task: items and bytes done, of how many, and since when."""

    def __init__(
        self,
        name: str,
        items: int | None = None,
        progress: Callable[[], int] | None = None,
    ) -> None:
        """
        Start the clock for a task.

        :param name: Short name printed in the status line.
        :param items: How many items (files, days) it handles, when known.
        :param progress: Reads the items done, for work counted in other processes. Defaults to
            None, meaning `item_done` counts them.
        """
        self.name = name
        self.items_total = items
        self.items_done = 0
        self.items_before = 0  # already on disk: counted as done, kept out of the ETA's pace
        self.progress = progress
        self.detail: Callable[[], str] | None = None
        self.bytes_done = 0
        self.bytes_expected = 0
        self.sizes_known = 0
        self.state = "pending"
        self.note = ""
        self.started = time.monotonic()
        self.ended: float | None = None
        self.lock = threading.Lock()

    def expect(self, size: int) -> None:
        """
        Record the size of a file about to be fetched.

        :param size: Its size in bytes.

        :returns: None.
        """
        with self.lock:
            self.bytes_expected += size
            self.sizes_known += 1

    def add_bytes(self, size: int) -> None:
        """
        Record bytes received.

        :param size: How many, negative to take back a failed attempt.

        :returns: None.
        """
        with self.lock:
            self.bytes_done += size

    def item_done(self) -> None:
        """
        Record one item finished.

        :returns: None.
        """
        with self.lock:
            self.items_done += 1

    def item_found(self) -> None:
        """
        Record one item already on disk from an earlier run: done, but not part of this run's pace.

        :returns: None.
        """
        with self.lock:
            self.items_done += 1
            self.items_before += 1

    def set_state(self, state: str, note: str | None = None) -> None:
        """
        Set what the task is doing, for the status line.

        :param state: A word such as `running`.
        :param note: Extra text, or None to keep the current one.

        :returns: None.
        """
        with self.lock:
            self.state = state
            if note is not None:
                self.note = note

    def finish(self, state: str = "done", note: str = "") -> None:
        """
        Stop the clock.

        :param state: `done`, `skipped` or `failed`.
        :param note: Why, or what it produced.

        :returns: None.
        """
        with self.lock:
            self.state, self.note, self.ended = state, note, time.monotonic()

    def line(self) -> str:
        """
        Describe the task in a few words, with an ETA when one can be computed.

        :returns text: The status fragment.
        """
        with self.lock:
            elapsed = (self.ended or time.monotonic()) - self.started
            if self.ended is not None:
                note = f" ({self.note})" if self.note else ""
                return f"{self.name} {self.state} in {fmt_duration(elapsed)}{note}"
            done = self.progress() if self.progress else self.items_done
            parts = [self.name]
            if self.items_total:
                parts.append(f"{done}/{self.items_total}")
            if self.bytes_done:
                parts.append(f"{self.bytes_done / 1e6:.1f} MB")
            fraction = 0.0
            if self.items_total and self.sizes_known == self.items_total and self.bytes_expected:
                fraction = self.bytes_done / self.bytes_expected
            elif self.items_total and done > self.items_before:
                fraction = (done - self.items_before) / (self.items_total - self.items_before)
            if 0 < fraction < 1:
                parts.append(f"ETA {fmt_duration(elapsed * (1 - fraction) / fraction)}")
            else:
                parts.append(f"{self.state} {fmt_duration(elapsed)}")
            extra = ", ".join(text for text in (self.note, self.detail and self.detail()) if text)
            if extra:
                parts.append(f"({extra})")
            return " ".join(parts)


def report(jobs: list[Job], started: float, stop: threading.Event, every: float) -> None:
    """
    Print one status line for all tasks every few seconds until told to stop.

    :param jobs: The tasks.
    :param started: When they began.
    :param stop: Set when every task has finished.
    :param every: Seconds between lines.

    :returns: None.
    """
    while not stop.wait(every):
        status = " | ".join(job.line() for job in jobs)
        print(f"[{fmt_duration(time.monotonic() - started)}] {status}", flush=True)


def fetch(url: str, dest: Path, job: Job) -> bool:
    """
    Stream a URL to a file, atomically, retrying transient failures.

    A file already on disk is kept, so an interrupted download resumes where it stopped.

    :param url: What to fetch.
    :param dest: Where to write it.
    :param job: Receives the expected and received bytes.

    :returns found: False when the server has no such file (HTTP 403 or 404).
    :raises urllib.error.URLError: When every attempt fails.
    """
    if dest.exists():
        job.expect(dest.stat().st_size)
        job.add_bytes(dest.stat().st_size)
        return True
    tmp = dest.with_name(dest.name + ".part")
    for attempt in range(1, RETRIES + 1):
        received = 0
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response, open(tmp, "wb") as out:
                size = response.headers.get("Content-Length")
                if size and attempt == 1:
                    job.expect(int(size))
                while chunk := response.read(1 << 20):
                    out.write(chunk)
                    received += len(chunk)
                    job.add_bytes(len(chunk))
            tmp.replace(dest)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return False
            if attempt == RETRIES:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == RETRIES:
                raise
        job.add_bytes(-received)
        time.sleep(2**attempt)
    return False


def download_gwa(gwa_dir: Path, heights: list[int], job: Job) -> None:
    """
    Fetch the GWA mean wind speed GeoTIFF for Romania at each height, in parallel.

    :param gwa_dir: Where the files go.
    :param heights: Heights above ground, in metres.
    :param job: Progress.

    :returns: None.
    :raises FileNotFoundError: When GWA has no file for a height.
    """
    gwa_dir.mkdir(parents=True, exist_ok=True)
    job.set_state("running")

    def one(height: int) -> None:
        if not fetch(GWA_URL.format(height=height), gwa_dir / f"ro_ws_{height}m.tif", job):
            raise FileNotFoundError(f"GWA has no wind-speed layer at {height} m")
        job.item_done()

    with ThreadPoolExecutor(len(heights)) as pool:
        list(pool.map(one, heights))
    job.finish("done", f"{job.bytes_done / 1e6:.0f} MB")


def dem_tile_names() -> list[str]:
    """
    Name the Copernicus GLO-90 tiles that cover Romania's bounding box.

    :returns names: One name per 1x1 degree tile.
    """
    return [
        f"Copernicus_DSM_COG_30_N{lat}_00_E{lon:03d}_00_DEM" for lat in DEM_LATS for lon in DEM_LONS
    ]


def download_dem(dem_dir: Path, job: Job) -> None:
    """
    Fetch the elevation tiles, sixteen at a time. Sea-only tiles do not exist and are skipped.

    :param dem_dir: Where the tiles go.
    :param job: Progress.

    :returns: None.
    """
    dem_dir.mkdir(parents=True, exist_ok=True)
    job.set_state("running")
    absent = []

    def one(name: str) -> None:
        if not fetch(DEM_URL.format(name=name), dem_dir / f"{name}.tif", job):
            absent.append(name)
        job.item_done()

    with ThreadPoolExecutor(DEM_WORKERS) as pool:
        list(pool.map(one, dem_tile_names()))
    job.finish("done", f"{job.bytes_done / 1e6:.0f} MB, {len(absent)} sea-only tiles absent")


def era5_available_until() -> tuple[int, int] | None:
    """
    Ask the CDS catalogue for the last month of ERA5 that is complete.

    Requesting a month that does not exist yet is an invalid request, and ECMWF may disable
    accounts that keep submitting those, so the newest months are never guessed.

    :returns year_month: The last complete (year, month), or None when the catalogue cannot be read.
    """
    import datetime
    import json

    url = "https://cds.climate.copernicus.eu/api/catalogue/v1/collections/" + ERA5_DATASET
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            interval = json.load(response)["extent"]["temporal"]["interval"][0]
        end = datetime.datetime.fromisoformat(interval[1])
    except Exception:  # offline or a changed catalogue: the caller decides what to do
        return None
    # The interval ends at the first instant without data: the month before it is the last whole one.
    last_day = end - datetime.timedelta(microseconds=1)
    if last_day.month == (last_day + datetime.timedelta(days=1)).month:
        last_day = last_day.replace(day=1) - datetime.timedelta(days=1)  # that month is partial
    return last_day.year, last_day.month


def era5_chunks(
    years: list[int], months_per_request: int, until: tuple[int, int] | None
) -> list[tuple[int, int, int]]:
    """
    List the CDS requests of a span of years, newest first, as (year, first month, last month).

    :param years: The years.
    :param months_per_request: Months in each request, a divisor of 12.
    :param until: The last complete (year, month) of ERA5; later months are left out. None keeps
        every month.

    :returns chunks: One triple per request, the most recent first.
    """
    chunks = []
    for year in years:
        for first in range(1, 13, months_per_request):
            last = first + months_per_request - 1
            if until and (year, first) > until:
                continue
            if until and (year, last) > until:
                last = until[1]
            chunks.append((year, first, last))
    return sorted(chunks, reverse=True)


def era5_needed_months(years: list[int], until: tuple[int, int] | None) -> list[tuple[int, int]]:
    """
    List the (year, month) pairs that should be on disk.

    :param years: The years.
    :param until: The last complete (year, month) of ERA5, or None for every month.

    :returns months: In calendar order.
    """
    months = [(year, month) for year in years for month in range(1, 13)]
    return [pair for pair in months if until is None or pair <= until]


def era5_chunk_path(hourly_dir: Path, year: int, first: int, last: int) -> Path:
    """
    Name the hourly ERA5 file of one request.

    :param hourly_dir: Where the files live.
    :param year: The year.
    :param first: The request's first month, 1 to 12.
    :param last: Its last month.

    :returns path: The file.
    """
    return hourly_dir / f"era5_{year}_{first:02d}-{last:02d}.nc"


def era5_files(hourly_dir: Path) -> dict[tuple[int, int], Path]:
    """
    Map each (year, month) to a file on disk that holds it, whatever request size fetched it.

    Files from different request sizes may be mixed, so a run can switch sizes and resume.

    :param hourly_dir: Where the files live.

    :returns covered: The file of each month present.
    """
    covered: dict[tuple[int, int], Path] = {}
    for path in sorted(hourly_dir.glob("era5_*.nc")):
        match = ERA5_FILE.fullmatch(path.name)
        if match:
            year, first, last = map(int, match.groups())
            for month in range(first, last + 1):
                covered.setdefault((year, month), path)
    return covered


def era5_request(year: int, first: int, last: int) -> dict[str, Any]:
    """
    Build the CDS request for every hour of some months, all four wind variables.

    :param year: The year.
    :param first: The first month, 1 to 12.
    :param last: The last month.

    :returns request: The request, as the CDS API takes it.
    """
    return {
        "product_type": ["reanalysis"],
        "variable": ERA5_VARIABLES,
        "year": [str(year)],
        "month": [f"{month:02d}" for month in range(first, last + 1)],
        "day": [f"{day:02d}" for day in range(1, 32)],
        "time": [f"{hour:02d}:00" for hour in range(24)],
        "area": ERA5_AREA,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def check_cds_size(request: dict[str, Any]) -> None:
    """
    Refuse a request the CDS would reject for its size, before submitting it.

    ECMWF may disable accounts that keep submitting invalid requests, so this asks the CDS for the
    request's cost, which submits nothing.

    :param request: The request.

    :returns: None.
    :raises ValueError: When the request is over the CDS size limit.
    """
    try:
        import cdsapi
        from ecmwf.datastores import Client

        url, key, _ = cdsapi.api.get_url_key_verify(None, None, None)
        costs = Client(url=url, key=key).estimate_costs(ERA5_DATASET, request)
    except Exception as exc:  # an older client without the estimate: say so and go on
        print(f"  [era5] request size not checked ({type(exc).__name__})", flush=True)
        return
    if costs.get("cost", 0) > costs.get("limit", float("inf")):
        raise ValueError(
            f"request size {costs['cost']:.0f} is over the CDS limit {costs['limit']:.0f}"
        )


def cds_credentials() -> bool:
    """
    Tell whether the CDS client will find credentials.

    :returns found: True when `~/.cdsapirc` exists or `CDSAPI_KEY` is set.
    """
    return Path("~/.cdsapirc").expanduser().is_file() or bool(os.environ.get("CDSAPI_KEY"))


def cds_callbacks(set_state: Callable[[str], None]) -> dict[str, Callable[..., None]]:
    """
    Build the CDS client's message callbacks: states go to `set_state`, problems are printed.

    Both the legacy and the current CDS client take these, so nothing depends on how either one
    configures logging.

    :param set_state: Receives `queued`, `running` or `downloading` as the request moves.

    :returns callbacks: Keyword arguments for `cdsapi.Client`.
    """

    def text(message: Any, *args: Any) -> str:
        return str(message) % args if args else str(message)

    def info(message: Any, *args: Any, **_: Any) -> None:
        lowered = text(message, *args).lower()
        for word, state in CDS_STATES.items():
            if f"status has been updated to {word}" in lowered:
                set_state(state)

    def problem(message: Any, *args: Any, **_: Any) -> None:
        print(f"  [era5] {text(message, *args)}", flush=True)

    return {"info_callback": info, "warning_callback": problem, "error_callback": problem}


def keep_netcdf(tmp: Path, path: Path) -> None:
    """
    Move a CDS download into place, unpacking it when the CDS sent a zip.

    :param tmp: The downloaded file.
    :param path: Where the NetCDF goes.

    :returns: None.
    :raises ValueError: When the zip holds other than one NetCDF.
    """
    if not zipfile.is_zipfile(tmp):
        tmp.replace(path)
        return
    with zipfile.ZipFile(tmp) as archive:
        members = [name for name in archive.namelist() if name.endswith(".nc")]
        if len(members) != 1:
            raise ValueError(f"expected one NetCDF in the CDS archive, found {members}")
        path.write_bytes(archive.read(members[0]))
    tmp.unlink()


def download_era5(
    hourly_dir: Path,
    years: list[int],
    months_per_request: int,
    until: tuple[int, int] | None,
    job: Job,
) -> None:
    """
    Fetch every hour of the years, newest month first, strictly one CDS request at a time.

    Since October 2026 ECMWF suspends accounts that submit requests in parallel or in large
    batches, so requests go one after another with a pause between them. The first failure stops
    the sequence rather than submitting more requests that may fail the same way; running again
    resumes with the months not yet on disk.

    :param hourly_dir: Where the files go.
    :param years: The years.
    :param months_per_request: Months in each request, a divisor of 12.
    :param until: The last complete (year, month) of ERA5, from the CDS catalogue.
    :param job: Progress.

    :returns: None.
    :raises RuntimeError: When the catalogue could not be read, or a request fails, naming it.
    """
    if not cds_credentials():
        job.finish("skipped", "no ~/.cdsapirc: create a free CDS account, see the docstring")
        return
    if until is None:
        raise RuntimeError("could not read ERA5's last available month from the CDS catalogue")
    import cdsapi  # only this step talks to the CDS

    hourly_dir.mkdir(parents=True, exist_ok=True)
    covered = era5_files(hourly_dir)
    job.add_bytes(sum(path.stat().st_size for path in set(covered.values())))
    todo = []
    for year, first, last in era5_chunks(years, months_per_request, until):
        if all((year, month) in covered for month in range(first, last + 1)):
            job.item_found()
        else:
            todo.append((year, first, last))
    if not todo:
        job.finish("done", "already on disk")
        return

    current = {"name": "", "state": ""}
    job.detail = lambda: f"{current['name']} {current['state']}".strip()
    job.set_state("running", f"one request at a time; {ERA5_TYPICAL}")
    check_cds_size(era5_request(*todo[0]))

    def set_state(state: str) -> None:
        current["state"] = state

    for index, (year, first, last) in enumerate(todo):
        if index:
            set_state(f"pausing {CDS_PAUSE_S} s")
            time.sleep(CDS_PAUSE_S)
        path = era5_chunk_path(hourly_dir, year, first, last)
        current["name"] = path.stem
        set_state("submitting")
        tmp = path.with_name(path.name + ".part")
        try:
            client = cdsapi.Client(quiet=True, progress=False, **cds_callbacks(set_state))
            client.retrieve(ERA5_DATASET, era5_request(year, first, last), str(tmp))
            keep_netcdf(tmp, path)
        except Exception as exc:  # stop: the next request would likely fail the same way
            raise RuntimeError(f"{path.stem}: {exc}; stopped, run again to resume") from exc
        job.add_bytes(path.stat().st_size)
        job.item_done()
        job.set_state("running", "one request at a time")
    current["name"] = current["state"] = ""
    job.finish("done", f"{job.items_total} requests, {job.bytes_done / 1e6:.0f} MB")


def run_job(job: Job, work: Callable[..., None], *args: Any) -> None:
    """
    Run one download, turning an exception into a failed job instead of a crash.

    :param job: The job the work reports to.
    :param work: The download function.
    :param args: Its arguments, the job last.

    :returns: None.
    """
    try:
        work(*args, job)
    except Exception as exc:  # report it in the status line; the other downloads go on
        job.finish("failed", f"{type(exc).__name__}: {exc}"[:300])


def download(
    data_dir: Path,
    heights: list[int],
    years: list[int],
    era5: bool,
    months_per_request: int,
    every: float,
) -> bool:
    """
    Run the three downloads at once, printing progress and ETAs. ERA5 requests go one at a time.

    :param data_dir: Where the data goes.
    :param heights: GWA heights to fetch.
    :param years: ERA5 years to fetch, every hour of them.
    :param era5: Whether to request ERA5 at all.
    :param months_per_request: Months in each ERA5 request, a divisor of 12.
    :param every: Seconds between status lines.

    :returns ok: False when a download failed.
    """
    until = era5_available_until() if era5 else None
    requests = len(era5_chunks(years, months_per_request, until))
    months = len(era5_needed_months(years, until))
    jobs = [Job("gwa", len(heights)), Job("dem", len(dem_tile_names())), Job("era5", requests)]
    gwa, dem, era = jobs
    newest = f"{until[0]}-{until[1]:02d}" if until else "unknown"
    print(
        f"Plan: gwa {len(heights)} files x ~18 MB | dem {dem.items_total} tiles, ~300 MB, "
        f"{DEM_WORKERS} at a time | era5 hourly, {months} months up to {newest}, newest first: "
        f"{requests} requests of {months_per_request} months, one at a time, ~{months * 9} MB. "
        f"Status every {every:g} s.",
        flush=True,
    )
    started = time.monotonic()
    stop = threading.Event()
    printer = threading.Thread(target=report, args=(jobs, started, stop, every), daemon=True)
    printer.start()
    with ThreadPoolExecutor(len(jobs)) as pool:
        pool.submit(run_job, gwa, download_gwa, data_dir / "gwa", heights)
        pool.submit(run_job, dem, download_dem, data_dir / "dem")
        if era5:
            hourly_dir = data_dir / "era5" / "hourly"
            pool.submit(run_job, era, download_era5, hourly_dir, years, months_per_request, until)
        else:
            era.finish("skipped", "--no-era5")
    stop.set()
    printer.join()
    print(f"[{fmt_duration(time.monotonic() - started)}] " + " | ".join(j.line() for j in jobs))
    return all(job.state != "failed" for job in jobs)


def elevation_on_grid(dem_dir: Path, crs: Any, transform: Any, shape: tuple[int, int]) -> Any:
    """
    Mosaic the DEM tiles and average them onto the GWA grid.

    :param dem_dir: Where the tiles are.
    :param crs: The GWA grid's CRS.
    :param transform: The GWA grid's affine transform.
    :param shape: The GWA grid's (rows, columns).

    :returns elevation: Metres above sea level per GWA pixel, NaN where no tile covers it.
    :raises SystemExit: When there are no tiles.
    """
    import numpy as np  # heavy: imported only by the steps that compute
    import rasterio
    from rasterio.merge import merge
    from rasterio.transform import array_bounds
    from rasterio.warp import Resampling, reproject, transform_bounds

    paths = sorted(dem_dir.glob("*.tif"))
    if not paths:
        raise SystemExit(f"No DEM tiles in {dem_dir}: run `download` first.")
    sources = [rasterio.open(path) for path in paths]
    try:
        dem_crs = sources[0].crs
        bounds = transform_bounds(crs, dem_crs, *array_bounds(*shape, transform))
        mosaic, mosaic_transform = merge(sources, bounds=bounds, dtype="float32", nodata=np.nan)
    finally:
        for source in sources:
            source.close()
    elevation = np.full(shape, np.nan, dtype="float32")
    reproject(
        mosaic[0],
        elevation,
        src_transform=mosaic_transform,
        src_crs=dem_crs,
        src_nodata=np.nan,
        dst_transform=transform,
        dst_crs=crs,
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    return elevation


def linear_weights(source: Any, target: Any) -> Any:
    """
    Build the matrix that linearly interpolates values on `source` coordinates onto `target`.

    Two of them, one per axis, make bilinear interpolation a pair of matrix products, which is what
    lets every day of ten years be put on the 250 m grid in minutes. Beyond the source's edges the
    edge value is held.

    :param source: Coordinates of the coarse grid along one axis, in any order.
    :param target: Coordinates of the fine grid along the same axis.

    :returns weights: A (len(target), len(source)) float32 matrix whose rows sum to 1.
    """
    import numpy as np

    order = np.argsort(source)
    ascending = np.asarray(source)[order]
    left = np.clip(np.searchsorted(ascending, target) - 1, 0, len(ascending) - 2)
    span = ascending[left + 1] - ascending[left]
    fraction = np.clip((np.asarray(target) - ascending[left]) / span, 0.0, 1.0)
    weights = np.zeros((len(target), len(source)), dtype=np.float32)
    rows = np.arange(len(target))
    weights[rows, order[left]] = 1 - fraction
    weights[rows, order[left + 1]] += fraction
    return weights


def era5_daily(
    hourly_dir: Path, years: list[int], until: tuple[int, int] | None, cache: Path
) -> tuple[Any, list[str]]:
    """
    Turn the hourly ERA5 files into daily mean wind speed at 100 m and 10 m, cached on disk.

    Speed is computed every hour from u and v, then averaged: averaging u and v first would cancel
    winds that turn and understate the speed.

    :param hourly_dir: Where the hourly files are.
    :param years: The years.
    :param until: The last complete (year, month) of ERA5; later months are not expected. None
        expects every month of every year.
    :param cache: Where the daily file goes.

    :returns daily_missing: The daily dataset (`ws100`, `ws10` over time, latitude, longitude), or
        None when months are missing; and the missing months, as `YYYY-MM`.
    """
    import numpy as np
    import xarray as xr

    covered = era5_files(hourly_dir)
    needed = era5_needed_months(years, until)
    missing = [f"{year}-{month:02d}" for year, month in needed if (year, month) not in covered]
    if missing:
        return None, missing
    paths = sorted({covered[key] for key in needed})
    newest = max(path.stat().st_mtime for path in paths)
    if cache.exists() and cache.stat().st_mtime >= newest:
        with xr.open_dataset(cache) as dataset:
            return dataset.load(), []
    parts = []
    for path in paths:
        with xr.open_dataset(path) as dataset:
            hourly = dataset.load()
        time_dim = "valid_time" if "valid_time" in hourly.dims else "time"
        hourly = hourly.drop_vars([name for name in hourly.coords if name not in hourly.dims])
        speeds = xr.Dataset(
            {
                "ws100": np.hypot(hourly["u100"], hourly["v100"]),
                "ws10": np.hypot(hourly["u10"], hourly["v10"]),
            }
        )
        for dim in set(speeds.dims) - {time_dim, "latitude", "longitude"}:
            speeds = speeds.mean(dim, skipna=True)  # e.g. `expver`, split between ERA5 and ERA5T
        parts.append(speeds.resample({time_dim: "1D"}).mean().rename({time_dim: "time"}))
    daily = xr.concat(parts, "time").sortby("time").transpose("time", "latitude", "longitude")
    # Files of different request sizes may overlap: keep each day once, and only the years asked.
    daily = daily.isel(time=~daily.get_index("time").duplicated())
    daily = daily.sel(time=slice(f"{years[0]}-01-01", f"{years[-1]}-12-31"))
    daily["ws100"].attrs = {"units": "m s-1", "long_name": "daily mean wind speed at 100 m"}
    daily["ws10"].attrs = {"units": "m s-1", "long_name": "daily mean wind speed at 10 m"}
    tmp = cache.with_name(cache.name + ".part")
    daily.to_netcdf(tmp)
    tmp.replace(cache)
    return daily, []


def era5_factors(speed: Any, w_lat: Any, w_lon: Any) -> dict[str, Any]:
    """
    Turn daily ERA5 speeds into ratios to the multi-year mean, on the GWA grid.

    :param speed: Daily mean speed (time, latitude, longitude).
    :param w_lat: Interpolation weights from ERA5 to GWA latitudes.
    :param w_lon: Interpolation weights from ERA5 to GWA longitudes.

    :returns factors: `monthly` (12 arrays), `p10` and `p90` (one array each, the 10th and 90th
        percentile of the yearly mean), `years` (how many complete years went in).
    """
    import numpy as np

    mean = speed.mean("time")
    months = speed.groupby("time.month").mean() / mean
    complete = [
        year
        for year, group in speed.groupby("time.year")
        if len(np.unique(group["time"].dt.month)) == 12
    ]
    yearly = speed.groupby("time.year").mean().sel(year=complete) / mean

    def on_grid(field: Any) -> Any:
        values = field.transpose("latitude", "longitude").values.astype(np.float32)
        return w_lat @ values @ w_lon.T

    return {
        "monthly": [on_grid(months.sel(month=month)) for month in range(1, 13)],
        "p10": on_grid(yearly.quantile(0.1, dim="year")),
        "p90": on_grid(yearly.quantile(0.9, dim="year")),
        "years": len(complete),
    }


def _init_worker(counter: Any, grid: dict[str, Any]) -> None:
    """
    Give a worker process the grid it shares with the others, once.

    :param counter: A shared integer, days written so far, for the ETA.
    :param grid: `speed`, `band`, `w_lat`, `w_lon`, `lat`, `lon`, `long_name`.

    :returns: None.
    """
    _WORKER.update(grid, counter=counter)


def write_daily_year(path: Path, dates: Any, ratio: Any) -> None:
    """
    Write one year of daily 250 m wind speed, 200-800 m pixels only, as compressed NetCDF.

    Runs in a worker process. Each day is the GWA mean times that day's ERA5 ratio, interpolated.

    :param path: Where the file goes.
    :param dates: The days (datetime64[D]).
    :param ratio: Each day's ERA5 speed over its ten-year mean (days, latitude, longitude).

    :returns: None.
    """
    import netCDF4
    import numpy as np

    speed, band = _WORKER["speed"], _WORKER["band"]
    w_lat, w_lon_t = _WORKER["w_lat"], _WORKER["w_lon"].T
    counter = _WORKER["counter"]
    tmp = path.with_name(path.name + ".part")
    with netCDF4.Dataset(tmp, "w", format="NETCDF4") as out:
        out.Conventions = "CF-1.8"
        out.title = _WORKER["long_name"]
        out.createDimension("time", len(dates))
        out.createDimension("lat", len(_WORKER["lat"]))
        out.createDimension("lon", len(_WORKER["lon"]))
        times = out.createVariable("time", "i4", ("time",))
        times.units, times.calendar, times.standard_name = (
            "days since 1970-01-01",
            "standard",
            "time",
        )
        times[:] = dates.astype("datetime64[D]").astype("int64")
        for name, values, units in (
            ("lat", _WORKER["lat"], "north"),
            ("lon", _WORKER["lon"], "east"),
        ):
            axis = out.createVariable(name, "f8", (name,))
            axis.units = f"degrees_{units}"
            axis.standard_name = "latitude" if name == "lat" else "longitude"
            axis[:] = values
        chunks = (1, min(512, len(_WORKER["lat"])), min(512, len(_WORKER["lon"])))
        wind = out.createVariable(
            "ws",
            "i2",
            ("time", "lat", "lon"),
            zlib=True,
            complevel=4,
            shuffle=True,
            chunksizes=chunks,
            fill_value=np.int16(-32768),
        )
        wind.scale_factor, wind.add_offset = 0.01, 0.0
        wind.units, wind.long_name = "m s-1", _WORKER["long_name"]
        for day in range(len(dates)):
            field = speed * (w_lat @ ratio[day] @ w_lon_t)
            # Zero, not NaN, under the mask: packing to int16 happens before the mask is applied.
            wind[day, :, :] = np.ma.array(np.where(band, field, 0.0), mask=~band)
            with counter.get_lock():
                counter.value += 1
    tmp.replace(path)


def daily_250m(
    out_dir: Path,
    speed_daily: Any,
    grid: dict[str, Any],
    years: list[int],
    workers: int,
    every: float,
) -> None:
    """
    Write every day of every year on the 250 m grid, one file per year, `workers` years at once.

    :param out_dir: Where the yearly files go.
    :param speed_daily: Daily ERA5 speed at the mapped height (time, latitude, longitude).
    :param grid: `speed`, `band`, `w_lat`, `w_lon`, `lat`, `lon` (cropped to the band), `height`,
        `long_name`.
    :param years: The years.
    :param workers: Processes.
    :param every: Seconds between status lines.

    :returns: None.
    """
    import numpy as np

    values = speed_daily.transpose("time", "latitude", "longitude").values
    ratio = (values / values.mean(axis=0)).astype(np.float32)
    dates = speed_daily["time"].values.astype("datetime64[D]")
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks, already = [], 0
    for year in years:
        pick = (dates >= np.datetime64(f"{year}-01-01")) & (
            dates < np.datetime64(f"{year + 1}-01-01")
        )
        if not pick.any():
            continue
        last = str(dates[pick][-1])[5:]
        # A year still in progress is named by its last day, so a later run writes a fresh file.
        suffix = "" if last == "12-31" else f"_to_{last}"
        path = out_dir / f"wind{grid['height']}_daily_{year}{suffix}.nc"
        if path.exists():
            already += int(pick.sum())
        else:
            tasks.append((path, dates[pick], ratio[pick]))
    if not tasks:
        print(f"  daily 250 m files already on disk: {out_dir}", flush=True)
        return

    counter = multiprocessing.Value("i", 0)
    job = Job("daily 250m", len(dates), progress=lambda: already + counter.value)
    job.items_before = already
    job.set_state("running", f"{min(workers, len(tasks))} processes")
    shared = {key: grid[key] for key in ("speed", "band", "w_lat", "w_lon", "lat", "lon")}
    shared["long_name"] = grid["long_name"]
    started = time.monotonic()
    stop = threading.Event()
    printer = threading.Thread(target=report, args=([job], started, stop, every), daemon=True)
    printer.start()
    try:
        with ProcessPoolExecutor(
            min(workers, len(tasks)), initializer=_init_worker, initargs=(counter, shared)
        ) as pool:
            for future in [pool.submit(write_daily_year, *task) for task in tasks]:
                future.result()
        size = sum(path.stat().st_size for path in out_dir.glob("*.nc")) / 1e9
        job.finish("done", f"{len(dates)} days, {size:.1f} GB in {out_dir}")
    except BaseException as exc:
        job.finish("failed", f"{type(exc).__name__}: {exc}"[:300])
        raise
    finally:
        stop.set()
        printer.join()
        print(f"  {job.line()}", flush=True)


def write_tif(path: Path, bands: list[Any], crs: Any, transform: Any) -> None:
    """
    Write float32 bands as one compressed GeoTIFF, NaN as nodata.

    :param path: Where.
    :param bands: 2-D arrays of the same shape.
    :param crs: Their CRS.
    :param transform: Their affine transform.

    :returns: None.
    """
    import numpy as np
    import rasterio

    stack = np.stack(bands).astype("float32")
    profile = {
        "driver": "GTiff",
        "height": stack.shape[1],
        "width": stack.shape[2],
        "count": stack.shape[0],
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": np.nan,
        "compress": "deflate",
        "predictor": 3,
        "tiled": True,
    }
    with rasterio.open(path, "w", **profile) as out:
        out.write(stack)


def draw_maps(
    path: Path, panels: list[tuple[str, Any]], context: dict[str, Any], title: str, cols: int
) -> None:
    """
    Draw one or more Romania maps on a shared colour scale and save them as a PNG.

    Inside the band each pixel takes the blue ramp; the rest of Romania is flat grey, so the band's
    shape reads at a glance and the colour carries only wind speed.

    :param path: Where the PNG goes.
    :param panels: (label, 2-D wind speed) per map.
    :param context: `land`, `band`, `crop`, `extent`, `subtitle`, `stride`.
    :param title: The figure title.
    :param cols: Maps per row.

    :returns: None.
    """
    import matplotlib

    matplotlib.use("Agg")  # files only, no window
    from matplotlib.colors import LinearSegmentedColormap, ListedColormap, Normalize
    from matplotlib.patches import Patch
    import matplotlib.pyplot as plt
    import numpy as np

    stride, band, crop, extent = (
        context["stride"],
        context["band"],
        context["crop"],
        context["extent"],
    )
    inside = np.concatenate([values[band] for _, values in panels])
    low, high = np.nanpercentile(inside, [2, 98])
    norm = Normalize(vmin=np.floor(low * 2) / 2, vmax=np.ceil(high * 2) / 2)
    ramp = LinearSegmentedColormap.from_list("wind", RAMP)
    ramp.set_bad((0, 0, 0, 0))
    grey = ListedColormap([OUT_OF_BAND])
    grey.set_bad((0, 0, 0, 0))
    base = np.where(context["land"], 1.0, np.nan)[crop][::stride, ::stride]

    # The layout is fixed in inches: each map box has Romania's true shape, so nothing is left over.
    west, east, south, north = extent
    ratio = (east - west) * np.cos(np.deg2rad((south + north) / 2)) / (north - south)
    rows = -(-len(panels) // cols)
    map_w = {1: 8.5, 3: 4.2}.get(cols, 3.2)
    map_h = map_w / ratio
    label_h = 0.3 if any(label for label, _ in panels) else 0.0
    left, gap, head, foot, bar_w = 0.3, 0.2, 0.95, 0.45, 1.1
    width = left + cols * map_w + (cols - 1) * gap + bar_w
    maps_h = rows * (label_h + map_h) + (rows - 1) * gap
    height = head + maps_h + foot
    fig = plt.figure(figsize=(width, height))
    image = None
    for index, (label, values) in enumerate(panels):
        row, col = divmod(index, cols)
        x = left + col * (map_w + gap)
        top = head + row * (label_h + map_h + gap) + label_h
        ax = fig.add_axes((x / width, 1 - (top + map_h) / height, map_w / width, map_h / height))
        ax.imshow(base, extent=extent, cmap=grey, interpolation="nearest", aspect="auto")
        shown = np.where(band, values, np.nan)[crop][::stride, ::stride]
        image = ax.imshow(shown, extent=extent, cmap=ramp, norm=norm, aspect="auto")
        ax.set_axis_off()
        if label:
            ax.set_title(label, color=INK, fontsize=11, loc="left", pad=4)

    bar_box = ((width - bar_w + 0.15) / width, 1 - (head + 0.9 * maps_h) / height)
    cax = fig.add_axes((*bar_box, 0.18 / width, 0.8 * maps_h / height))
    bar = fig.colorbar(image, cax=cax)
    bar.set_label("viteza medie a vântului, m/s", color=MUTED)
    bar.outline.set_visible(False)
    bar.ax.tick_params(colors=MUTED)
    fig.text(left / width, 1 - 0.4 / height, title, color=INK, fontsize=14, fontweight="bold")
    fig.text(left / width, 1 - 0.68 / height, context["subtitle"], color=MUTED, fontsize=9)
    fig.legend(
        handles=[Patch(color=OUT_OF_BAND, label="România, în afara benzii de altitudine")],
        loc="lower left",
        bbox_to_anchor=(left / width - 0.01, 0.05 / height),
        frameon=False,
        fontsize=9,
        labelcolor=MUTED,
    )
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def build(
    data_dir: Path,
    height: int,
    elev_min: float,
    elev_max: float,
    years: list[int],
    workers: int,
    daily_files: bool,
    every: float,
) -> None:
    """
    Turn the downloads into daily 250 m files, GeoTIFFs, heatmaps and a summary.

    :param data_dir: Where the downloads are.
    :param height: GWA height to map, in metres: 100 uses ERA5's 100 m wind, others its 10 m wind.
    :param elev_min: Lowest terrain elevation kept, in metres above sea level.
    :param elev_max: Highest terrain elevation kept.
    :param years: The ERA5 years.
    :param workers: Processes writing the daily files.
    :param daily_files: Whether to write the daily 250 m files.
    :param every: Seconds between status lines.

    :returns: None.
    :raises SystemExit: When the GWA file is missing or not on a geographic grid.
    """
    import numpy as np
    import rasterio

    started = time.monotonic()

    def step(text: str) -> None:
        print(f"[{fmt_duration(time.monotonic() - started)}] {text}", flush=True)

    gwa_path = data_dir / "gwa" / f"ro_ws_{height}m.tif"
    if not gwa_path.exists():
        raise SystemExit(f"No {gwa_path}: run `download --heights {height}` first.")
    with rasterio.open(gwa_path) as gwa:
        speed = gwa.read(1, masked=True).astype("float32").filled(np.nan)
        crs, transform = gwa.crs, gwa.transform
    if not crs.is_geographic:
        raise SystemExit(f"{gwa_path} is not on a longitude/latitude grid ({crs}).")
    rows, cols = speed.shape
    lon = transform.c + (np.arange(cols) + 0.5) * transform.a
    lat = transform.f + (np.arange(rows) + 0.5) * transform.e
    dx = abs(transform.a) * 111_320 * np.cos(np.deg2rad(lat.mean()))
    step(
        f"GWA {height} m: {rows} x {cols} pixels of ~{dx:.0f} x {abs(transform.e) * 110_570:.0f} m"
    )

    elevation = elevation_on_grid(data_dir / "dem", crs, transform, speed.shape)
    # GWA's Romania file also covers its Black Sea waters; the DEM puts the sea at exactly 0 m.
    land = np.isfinite(speed) & (elevation > 0)
    band = land & (elevation >= elev_min) & (elevation <= elev_max)
    step(f"Elevation on the GWA grid; {band.sum():,} pixels in {elev_min:.0f}-{elev_max:.0f} m")
    land_rows, land_cols = np.flatnonzero(land.any(axis=1)), np.flatnonzero(land.any(axis=0))
    crop = (slice(land_rows[0], land_rows[-1] + 1), slice(land_cols[0], land_cols[-1] + 1))
    half_x, half_y = abs(transform.a) / 2, abs(transform.e) / 2

    out = data_dir / "out"
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{height}m_{elev_min:.0f}-{elev_max:.0f}m"
    write_tif(out / f"wind_{tag}_mean.tif", [np.where(band, speed, np.nan)], crs, transform)

    row_km2 = abs(transform.a) * 111.32 * np.cos(np.deg2rad(lat)) * abs(transform.e) * 110.57
    country_km2 = float((land.sum(axis=1) * row_km2).sum())
    band_km2 = float((band.sum(axis=1) * row_km2).sum())
    rest = land & ~band
    summary = [
        f"Romania (land) mapped: {country_km2:,.0f} km2; {elev_min:.0f}-{elev_max:.0f} m band: "
        f"{band_km2:,.0f} km2 ({band_km2 / country_km2:.0%})",
        f"Mean wind at {height} m (GWA long-term): band {np.nanmean(speed[band]):.2f} m/s, "
        f"rest of Romania {np.nanmean(speed[rest]):.2f} m/s",
        f"Band, windiest 10% of pixels: above {np.nanpercentile(speed[band], 90):.2f} m/s",
    ]

    context = {
        "land": land,
        "band": band,
        "crop": crop,
        "extent": (
            lon[crop[1].start] - half_x,
            lon[crop[1].stop - 1] + half_x,
            lat[crop[0].stop - 1] - half_y,
            lat[crop[0].start] + half_y,
        ),
        "stride": 2,
        "subtitle": f"Teren {elev_min:.0f}–{elev_max:.0f} m · Global Wind Atlas 3, 250 m · "
        "harta arată anul tipic (climatul), nu un an anume",
    }
    title = f"Vântul de așteptat la {height} m într-un an tipic"
    draw_maps(out / f"heatmap_{tag}_mean.png", [("", speed)], context, title, cols=1)
    step("Mean map written")

    hourly_dir = data_dir / "era5" / "hourly"
    until = era5_available_until()
    if until is None:  # offline: the newest month on disk is the best guess of what exists
        on_disk = [key for key in era5_files(hourly_dir) if key[0] in years]
        until = max(on_disk) if on_disk else None
    cache = data_dir / "era5" / f"daily_{years[0]}-{years[-1]}.nc"
    daily, missing = era5_daily(hourly_dir, years, until, cache)
    if daily is None:
        step(
            f"ERA5: {len(missing)} of {len(era5_needed_months(years, until))} months missing "
            f"(e.g. {missing[0]}); run `download` to fetch them. Daily files, monthly and P10/P90 "
            "maps skipped."
        )
    else:
        variable = "ws100" if height == 100 else "ws10"
        speed_daily = daily[variable]
        step(f"ERA5: {daily.sizes['time']} days loaded; {variable} drives the variation")
        w_lat = linear_weights(daily["latitude"].values, lat)
        w_lon = linear_weights(daily["longitude"].values, lon)
        factors = era5_factors(speed_daily, w_lat, w_lon)
        n_years = factors["years"]
        monthly = [np.where(band, speed * factor, np.nan) for factor in factors["monthly"]]
        p10 = np.where(band, speed * factors["p10"], np.nan)
        p90 = np.where(band, speed * factors["p90"], np.nan)
        write_tif(out / f"wind_{tag}_monthly.tif", monthly, crs, transform)
        write_tif(out / f"wind_{tag}_p10.tif", [p10], crs, transform)
        write_tif(out / f"wind_{tag}_p90.tif", [p90], crs, transform)

        context["subtitle"] = (
            f"Teren {elev_min:.0f}–{elev_max:.0f} m · nivel: Global Wind Atlas 3 · "
            f"variație între ani: ERA5 orar, {n_years} ani"
        )
        spread = [("an slab (P10)", speed * factors["p10"]), ("an tipic", speed)]
        spread.append(("an puternic (P90)", speed * factors["p90"]))
        draw_maps(out / f"heatmap_{tag}_p10_p90.png", spread, context, title, cols=3)
        context["stride"] = 4
        context["subtitle"] = context["subtitle"].replace("variație între ani", "sezonalitate")
        by_month = [(name, speed * f) for name, f in zip(MONTHS_RO, factors["monthly"])]
        draw_maps(out / f"heatmap_{tag}_monthly.png", by_month, context, title + ", pe luni", 4)
        step(f"Monthly and P10/P90 maps written ({n_years} complete years)")
        low = np.nanmean(p10[band]) / np.nanmean(speed[band]) - 1
        high = np.nanmean(p90[band]) / np.nanmean(speed[band]) - 1
        summary.append(f"Yearly mean, P10 to P90 over {n_years} years: {low:+.1%} to {high:+.1%}")
        windiest = max(range(12), key=lambda m: np.nanmean(monthly[m][band]))
        calmest = min(range(12), key=lambda m: np.nanmean(monthly[m][band]))
        summary.append(f"Windiest month {MONTHS_RO[windiest]}, calmest {MONTHS_RO[calmest]}")

        # The band mean of each day is linear in that day's ERA5 ratio: one kernel gives all days.
        values = speed_daily.transpose("time", "latitude", "longitude").values
        ratio = values / values.mean(axis=0)
        kernel = w_lat.T @ np.where(band, speed, 0.0) @ w_lon / band.sum()
        band_mean = np.einsum("tij,ij->t", ratio, kernel)
        dates = speed_daily["time"].values.astype("datetime64[D]")
        csv = out / f"daily_band_mean_{tag}.csv"
        csv.write_text(
            "date,mean_wind_ms\n" + "".join(f"{d},{v:.3f}\n" for d, v in zip(dates, band_mean))
        )
        summary.append(
            f"Daily band mean over {len(dates)} days: {band_mean.min():.2f} to "
            f"{band_mean.max():.2f} m/s ({csv.name})"
        )
        step("Daily band means written")

        if daily_files:
            band_rows = np.flatnonzero(band.any(axis=1))
            band_cols = np.flatnonzero(band.any(axis=0))
            r = slice(band_rows[0], band_rows[-1] + 1)
            c = slice(band_cols[0], band_cols[-1] + 1)
            grid = {
                "speed": speed[r, c],
                "band": band[r, c],
                "w_lat": w_lat[r],
                "w_lon": w_lon[c],
                "lat": lat[r],
                "lon": lon[c],
                "height": height,
                "long_name": f"daily mean wind speed at {height} m on a 250 m grid (GWA long-term "
                f"mean x ERA5 daily ratio), terrain {elev_min:.0f}-{elev_max:.0f} m only",
            }
            step(f"Writing daily 250 m files: {len(dates)} days x {int(band.sum()):,} pixels")
            daily_250m(out / "daily_250m", speed_daily, grid, years, workers, every)

    (out / f"summary_{tag}.txt").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    step(f"Done: {out}")


def parse_years(text: str) -> list[int]:
    """
    Parse `2016-2025` or `2020` into a list of years.

    :param text: The span.

    :returns years: Every year in it, in order.
    :raises argparse.ArgumentTypeError: When the span runs backwards.
    """
    first, _, last = text.partition("-")
    start, end = int(first), int(last or first)
    if end < start:
        raise argparse.ArgumentTypeError(f"{text}: the span runs backwards")
    return list(range(start, end + 1))


def main(argv: list[str] | None = None) -> int:
    """
    Download the sources, build the outputs, or both.

    :param argv: Command-line arguments, defaulting to `sys.argv[1:]`.

    :returns code: 0 on success, 1 when a download failed.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip("# \n"))
    parser.add_argument("command", choices=["download", "build", "all"])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--heights", type=int, nargs="+", choices=GWA_HEIGHTS, default=[100, 150])
    parser.add_argument("--height", type=int, choices=GWA_HEIGHTS, default=100, help="mapped")
    parser.add_argument("--years", type=parse_years, default=parse_years("2016-2026"))
    parser.add_argument("--elev-min", type=float, default=200.0)
    parser.add_argument("--elev-max", type=float, default=800.0)
    parser.add_argument("--no-era5", action="store_true", help="skip the CDS requests")
    parser.add_argument(
        "--months-per-request",
        type=int,
        choices=[1, 2, 3, 6],
        default=MONTHS_PER_REQUEST,
        help="months in each ERA5 request; smaller requests may leave the CDS queue sooner",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 2) // 2),
        help="processes writing the daily 250 m files",
    )
    parser.add_argument("--no-daily-files", action="store_true", help="skip the daily 250 m files")
    parser.add_argument("--status-every", type=float, default=5.0, help="seconds")
    args = parser.parse_args(argv)

    ok = True
    if args.command in ("download", "all"):
        ok = download(
            args.data_dir,
            args.heights,
            args.years,
            not args.no_era5,
            args.months_per_request,
            args.status_every,
        )
    if args.command in ("build", "all"):
        build(
            args.data_dir,
            args.height,
            args.elev_min,
            args.elev_max,
            args.years,
            args.workers,
            not args.no_daily_files,
            args.status_every,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
