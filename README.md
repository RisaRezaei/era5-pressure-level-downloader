# ERA5 Pressure-Level Downloader

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Data: ERA5](https://img.shields.io/badge/data-ERA5%20monthly%20means-1565C0)](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels-monthly-means)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A small command-line tool to download **ERA5 monthly-mean data on pressure levels** (humidity, winds, temperature, geopotential and more) from the Copernicus Climate Data Store as NetCDF. Requests are split into one file per year and level, so long downloads queue well on the CDS and can be resumed after an interruption.

## Features

- Any years (`2022 2023` or ranges like `1990-2020`), months, pressure levels and variables
- Monthly means, or monthly means **by hour of day** (`00`, `06`, `12`, `18` UTC, …)
- Optional sub-region (`--area N W S E`) to keep files small
- Skips files already downloaded; retries failed requests
- `--dry-run` prints the exact CDS requests without downloading
- Settings from the command line or a TOML/JSON config file

## Installation

```bash
git clone https://github.com/RisaRezaei/era5-pressure-level-downloader.git
cd era5-pressure-level-downloader
pip install -r requirements.txt
```

### CDS credentials

1. Create a free account at the [Climate Data Store](https://cds.climate.copernicus.eu) and accept the ERA5 licence on the dataset page.
2. Put your API key in `~/.cdsapirc` (or set `CDSAPI_URL` / `CDSAPI_KEY`):

```text
url: https://cds.climate.copernicus.eu/api
key: <your-personal-access-token>
```

## Usage

```bash
# Nov–Apr 2022–2024, five levels, specific humidity + wind components
python era5_download.py --years 2022-2024 --months 11 12 1 2 3 4 \
    --levels 1000 850 700 500 300 \
    --variables specific_humidity u_component_of_wind v_component_of_wind

# Monthly means at 00/06/12/18 UTC over a sub-region
python era5_download.py --product monthly-by-hour --hours 00 06 12 18 \
    --area 45 40 25 65 --years 2023

# From a config file (see config.example.toml), checking the requests first
python era5_download.py --config config.example.toml --dry-run
python era5_download.py --config config.example.toml
```

### Options

| Option | Default | Description |
|---|---|---|
| `--years` | `2022-2024` | Years or ranges |
| `--months` | `11 12 1 2 3 4` | Month numbers |
| `--levels` | `1000 850 700 500 300` | Pressure levels (hPa) |
| `--variables` | humidity + u/v wind | CDS variable names |
| `--product` | `monthly` | `monthly` or `monthly-by-hour` |
| `--hours` | `00 06 12 18` | UTC hours (only with `monthly-by-hour`) |
| `--area N W S E` | global | Sub-region bounding box |
| `--split` | `year-level` | One file per year+level, per `year`, or `none` |
| `--out-dir` | `data/era5` | Output folder |
| `--overwrite` | off | Re-download existing files |
| `--dry-run` | off | Print requests only |

## Output

```text
data/era5/
├── ERA5_monthly_2022_1000hPa.nc
├── ERA5_monthly_2022_850hPa.nc
└── …
```

Open them with `xarray`:

```python
import xarray as xr
ds = xr.open_mfdataset("data/era5/ERA5_monthly_*_850hPa.nc", combine="by_coords")
```

## Notes

- Months are requested per calendar year, so a winter season such as Nov 2022 – Apr 2023 needs both 2022 and 2023 in `--years`.
- The CDS queue can be slow for big requests; the per-year/per-level split keeps each request small.

## Data and citation

Hersbach, H., Bell, B., Berrisford, P., et al. (2023). ERA5 monthly averaged data on pressure levels from 1940 to present. Copernicus Climate Change Service (C3S) Climate Data Store. https://doi.org/10.24381/cds.6860a573

## Author

**Parisa Abbasalizadehrezaei** · [risarezaei.github.io](https://risarezaei.github.io)

Released under the [MIT License](LICENSE).
