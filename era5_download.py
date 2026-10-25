#!/usr/bin/env python3
"""
ERA5 pressure-level downloader (monthly means) for the Copernicus Climate
Data Store (CDS).

Downloads ERA5 monthly-mean data on pressure levels, such as specific
humidity and wind components, as NetCDF. By default it writes one file per
year and pressure level, so large requests are split into chunks that the
CDS queue handles well, and an interrupted run can be resumed.

Examples
--------
    # Nov–Apr, 2022–2024, five levels, humidity + winds (the original use case)
    python era5_download.py --years 2022-2024 --months 11 12 1 2 3 4 \
        --levels 1000 850 700 500 300 \
        --variables specific_humidity u_component_of_wind v_component_of_wind

    # Same, but read everything from a config file
    python era5_download.py --config config.example.toml

    # Only print the requests, download nothing
    python era5_download.py --config config.example.toml --dry-run

Author: Parisa Abbasalizadehrezaei · https://risarezaei.github.io
License: MIT
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

DATASET = "reanalysis-era5-pressure-levels-monthly-means"
PRODUCTS = {
    "monthly": "monthly_averaged_reanalysis",
    "monthly-by-hour": "monthly_averaged_reanalysis_by_hour_of_day",
}
VALID_LEVELS = {
    1, 2, 3, 5, 7, 10, 20, 30, 50, 70, 100, 125, 150, 175, 200, 225, 250, 300,
    350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800, 825, 850, 875, 900,
    925, 950, 975, 1000,
}

log = logging.getLogger("era5")


# --------------------------------------------------------------------------
# Argument handling
# --------------------------------------------------------------------------
def parse_years(values: list[str]) -> list[int]:
    """Accept '2022 2023' and ranges like '2010-2015'."""
    years: list[int] = []
    for v in values:
        v = str(v)
        if "-" in v:
            a, b = (int(x) for x in v.split("-", 1))
            years.extend(range(min(a, b), max(a, b) + 1))
        else:
            years.append(int(v))
    return sorted(set(years))


def load_config(path: Path) -> dict:
    """Read a TOML or JSON config file."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore
    return tomllib.loads(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download ERA5 monthly-mean pressure-level data from the CDS.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", type=Path, help="TOML/JSON file with any of the options below")
    p.add_argument("--years", nargs="+", help="years or ranges, e.g. 2022-2024")
    p.add_argument("--months", nargs="+", type=int, help="month numbers 1-12")
    p.add_argument("--levels", nargs="+", type=int, help="pressure levels in hPa")
    p.add_argument("--variables", nargs="+", help="CDS variable names")
    p.add_argument("--product", choices=PRODUCTS, help="'monthly' or 'monthly-by-hour'")
    p.add_argument("--hours", nargs="+", help="UTC hours for 'monthly-by-hour', e.g. 00 06 12 18")
    p.add_argument("--area", nargs=4, type=float, metavar=("N", "W", "S", "E"),
                   help="sub-region bounding box; global if omitted")
    p.add_argument("--split", choices=["year-level", "year", "none"],
                   help="how to split requests into files")
    p.add_argument("--out-dir", type=Path, help="output folder")
    p.add_argument("--overwrite", action="store_true", help="re-download existing files")
    p.add_argument("--retries", type=int, help="retries per request")
    p.add_argument("--dry-run", action="store_true", help="print requests only")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


DEFAULTS = {
    "years": ["2022-2024"],
    "months": [11, 12, 1, 2, 3, 4],
    "levels": [1000, 850, 700, 500, 300],
    "variables": ["specific_humidity", "u_component_of_wind", "v_component_of_wind"],
    "product": "monthly",
    "hours": ["00", "06", "12", "18"],
    "area": None,
    "split": "year-level",
    "out_dir": "data/era5",
    "retries": 3,
}


def resolve_options(args: argparse.Namespace) -> dict:
    """Defaults < config file < command line."""
    opts = dict(DEFAULTS)
    if args.config:
        cfg = load_config(args.config)
        opts.update({k.replace("-", "_"): v for k, v in cfg.items()})
    for key in DEFAULTS:
        val = getattr(args, key, None)
        if val is not None:
            opts[key] = val

    opts["years"] = parse_years(opts["years"])
    opts["months"] = sorted({int(m) for m in opts["months"]})
    opts["levels"] = sorted({int(l) for l in opts["levels"]}, reverse=True)
    opts["out_dir"] = Path(opts["out_dir"])

    bad_m = [m for m in opts["months"] if not 1 <= m <= 12]
    bad_l = [l for l in opts["levels"] if l not in VALID_LEVELS]
    if bad_m:
        raise SystemExit(f"Invalid month(s): {bad_m}")
    if bad_l:
        raise SystemExit(f"Invalid pressure level(s): {bad_l}. Valid: {sorted(VALID_LEVELS)}")
    if opts["product"] not in PRODUCTS:
        raise SystemExit(f"Unknown product '{opts['product']}'")
    if opts["area"] is not None and len(opts["area"]) != 4:
        raise SystemExit("--area needs four numbers: N W S E")
    return opts


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------
def make_request(opts: dict, years: list[int], levels: list[int]) -> dict:
    req = {
        "product_type": [PRODUCTS[opts["product"]]],
        "variable": list(opts["variables"]),
        "pressure_level": [str(l) for l in levels],
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in opts["months"]],
        "time": (
            [f"{int(h):02d}:00" for h in opts["hours"]]
            if opts["product"] == "monthly-by-hour" else ["00:00"]
        ),
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    if opts["area"]:
        req["area"] = [float(x) for x in opts["area"]]
    return req


def plan_jobs(opts: dict) -> list[tuple[Path, dict]]:
    """Split the full request into (target file, request) jobs."""
    out, tag = opts["out_dir"], opts["product"].replace("-", "_")
    jobs = []
    if opts["split"] == "year-level":
        for y in opts["years"]:
            for l in opts["levels"]:
                jobs.append((out / f"ERA5_{tag}_{y}_{l}hPa.nc", make_request(opts, [y], [l])))
    elif opts["split"] == "year":
        for y in opts["years"]:
            jobs.append((out / f"ERA5_{tag}_{y}.nc", make_request(opts, [y], opts["levels"])))
    else:
        y0, y1 = opts["years"][0], opts["years"][-1]
        jobs.append((out / f"ERA5_{tag}_{y0}-{y1}.nc", make_request(opts, opts["years"], opts["levels"])))
    return jobs


def download(jobs: list[tuple[Path, dict]], overwrite: bool, retries: int) -> int:
    try:
        import cdsapi
    except ModuleNotFoundError:
        raise SystemExit("cdsapi is not installed: pip install -r requirements.txt")

    client = cdsapi.Client()  # reads ~/.cdsapirc or CDSAPI_URL / CDSAPI_KEY
    failed = 0
    for i, (target, req) in enumerate(jobs, 1):
        if target.exists() and not overwrite:
            log.info("[%d/%d] exists, skipping %s", i, len(jobs), target.name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        for attempt in range(1, retries + 1):
            try:
                log.info("[%d/%d] requesting %s (attempt %d)", i, len(jobs), target.name, attempt)
                client.retrieve(DATASET, req, str(tmp))
                tmp.replace(target)
                log.info("[%d/%d] saved %s", i, len(jobs), target)
                break
            except Exception as exc:  # network / queue errors from the CDS
                log.warning("request failed: %s", exc)
                if attempt == retries:
                    failed += 1
                    log.error("giving up on %s", target.name)
                else:
                    time.sleep(30 * attempt)
    return failed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    opts = resolve_options(args)
    jobs = plan_jobs(opts)
    log.info("%d request(s) planned -> %s", len(jobs), opts["out_dir"])

    if args.dry_run:
        for target, req in jobs:
            print(f"# {target}")
            print(json.dumps({"dataset": DATASET, "request": req}, indent=2))
        return 0

    failed = download(jobs, args.overwrite, int(opts["retries"]))
    if failed:
        log.error("%d request(s) failed", failed)
        return 1
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
