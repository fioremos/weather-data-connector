# Weather Data Integration Connector

A Python ETL connector that retrieves current weather from Open-Meteo, validates
the response with Pydantic, transforms it with Pandas, and writes a CSV and
comparison chart. The command-line interface and FastAPI service share the
same extraction and transformation pipeline.

## Architecture

See [the PlantUML architecture diagram](docs/diagram/architecture.png).

The flow follows:

1. The CLI or API validates city names, optional coordinate pairs, sorting, and
   the 50-city batch limit.
2. The extractor resolves missing coordinates and concurrently fetches
   forecasts. Each worker owns and closes its HTTPS-only `requests.Session`.
   Requests use explicit connect/read timeouts, disabled redirects, and
   retries for transient upstream failures.
3. Pydantic validates Open-Meteo's `results`, `current`, and `current_units`
   objects. Invalid or unavailable cities are logged and do not discard
   successful records from the batch.
4. Pandas deduplicates city names case-insensitively, converts units, and ranks
   the canonical output.
5. The CSV exporter neutralizes spreadsheet formula prefixes and atomically
   replaces its output file. The API also creates a headless Matplotlib chart.

## Project layout

```text
weather-data-connector/
├── app/
│   ├── api.py            # FastAPI health, run, CSV, and chart endpoints
│   ├── cli.py            # Bounded command-line entrypoint
│   ├── client.py         # HTTPS-only session and retry configuration
│   ├── exporter.py       # Formula-safe atomic CSV output
│   ├── extractor.py      # Geocoding and concurrent forecast retrieval
│   ├── models.py         # Input, upstream response, and domain models
│   ├── pipeline.py       # ETL orchestration
│   ├── transformer.py    # Unit conversion, deduplication, and ranking
│   └── visualizer.py     # Headless weather chart output
├── tests/                # Offline unit and API tests
├── output/               # Runtime CSV and chart artifacts
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Run locally with Python

From the workspace root:

```powershell
cd weather-data-connector
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.cli --cities "New York" Tokyo London --sort-by temperature_desc --output-dir output
```

The CLI also supports `--sort-by temperature_asc`, `humidity_asc`,
`humidity_desc`, `wind_asc`, `wind_desc`, or `city_asc`. It accepts at most
50 city names per run. Coordinates can be supplied through the API; CLI city
names are resolved with the Open-Meteo geocoding service.

## Run with Docker Compose

Build and run a one-off CLI task:

```powershell
cd weather-data-connector
docker compose build
docker compose run --rm weather-cli python -m app.cli --cities "New York" Tokyo --sort-by humidity_desc --output-dir /app/output
```

`docker compose run` uses the image's `python -m app.cli` command and forwards
the supplied CLI arguments. The mounted `./output` directory contains the
artifacts.

## Start the FastAPI server

Optionally configure API-key authentication by copying `.env.example` to `.env`
and setting a non-empty `API_KEY`. When the key is empty, the run endpoint is
open; when set, include it in the `X-API-Key` header.

```powershell
cd weather-data-connector
Copy-Item .env.example .env
docker compose up --build weather-api
```

The service listens on `http://localhost:8000`. The same server can be run
locally after installing requirements:

```powershell
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

### API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness status |
| `POST` | `/integrations/weather/run` | Run ETL and create CSV/chart |
| `GET` | `/integrations/weather/export` | Download the latest CSV |
| `GET` | `/integrations/weather/chart` | Render a PNG from the latest CSV |

Copyable examples:

```powershell
curl.exe http://localhost:8000/health
```

```powershell
curl.exe -X POST http://localhost:8000/integrations/weather/run `
  -H "Content-Type: application/json" `
  -H "X-API-Key: your-key-if-configured" `
  -d '{"cities":[{"city":"New York","latitude":40.7128,"longitude":-74.0060},{"city":"Tokyo"}],"sort_by":"temperature_desc","top_n":10}'
```

```powershell
curl.exe -o weather_data.csv http://localhost:8000/integrations/weather/export
```

```powershell
curl.exe -o weather_chart.png http://localhost:8000/integrations/weather/chart
```

The chart endpoint renders `bar` by default. Choose another Matplotlib layout
with `chart_type`:

```powershell
curl.exe -o weather_scatter.png "http://localhost:8000/integrations/weather/chart?chart_type=scatter"
curl.exe -o weather_dashboard.png "http://localhost:8000/integrations/weather/chart?chart_type=dashboard"
curl.exe -o weather_heatmap.png "http://localhost:8000/integrations/weather/chart?chart_type=heatmap"
```

Charts are generated on demand from `weather_data.csv` without calling
Open-Meteo again. If the CSV is missing or empty, the endpoint returns HTTP 404
and instructs you to run ingestion first.

The `X-API-Key` header is only required when `API_KEY` is configured. The run
request accepts `cities` (1-50 entries), optional paired `latitude` and
`longitude` values, `sort_by` (one of the CLI sort criteria), and optional
positive `top_n`. Invalid payloads receive HTTP 422; unavailable upstream
weather data returns HTTP 502; artifact downloads return HTTP 404 before the
first successful run.

## CSV output

The generated file is `output/weather_data.csv` locally and is stored in the
mounted output directory under Docker. Its exact ordered columns are:

| Column | Meaning |
|---|---|
| `City` | Requested city name |
| `Temperature (C)` | Current temperature in degrees Celsius |
| `Temperature (F)` | Converted temperature in degrees Fahrenheit |
| `Humidity (%)` | Current relative humidity percentage |
| `Wind Speed (m/s)` | Current wind speed in meters per second |
| `Wind Speed (mph)` | Converted wind speed in miles per hour |

Temperatures and wind speeds are rounded to two decimal places; humidity is
rounded to one decimal place. City names differing only in letter case produce
one row, retaining the most recently extracted record.

## Tests

Build the image and run the offline test suite in the container from the project
directory:

```powershell
cd weather-data-connector
docker compose build weather-cli
docker compose run --rm -v "${PWD}\tests:/tmp/tests:ro" weather-cli python -m pytest -v -p no:cacheprovider /tmp/tests
```

The tests cover transformation and ranking edge cases, CSV injection and path
confinement, HTTPS enforcement, API validation/authentication, and artifact
availability. Upstream calls are not required by the test suite.

## Code Quality & Linting

This repository keeps the Python package in `app/`. The
root `.pylintrc` targets Python 3.12 and enforces a 100-character line limit.
It also permits up to six function arguments and single-public-method
components used by the ETL pipeline. Run both linting and tests before
committing changes.

### Local virtual environment

```powershell
cd weather-data-connector
.\.venv\Scripts\Activate.ps1
pylint app tests --fail-under=9.5
pytest -v
```

### Docker

```powershell
cd weather-data-connector
docker compose build weather-cli
docker compose run --rm -v "${PWD}\app:/app/app:ro" -v "${PWD}\tests:/app/tests:ro" -v "${PWD}\.pylintrc:/app/.pylintrc:ro" weather-cli pylint app tests --fail-under=9.5
docker compose run --rm -v "${PWD}\tests:/tmp/tests:ro" weather-cli python -m pytest -v -p no:cacheprovider /tmp/tests
```
