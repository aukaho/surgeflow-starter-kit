# Templates

The Google Sheets starter workbook is hosted on the website and is not stored
in this repository. Download the current version here:

https://surgeflows.capital/templates/surgeflow-google-sheets-starter.xlsx

Open the Google Colab notebook for current-session turnover and hotlist tables:

https://colab.research.google.com/github/aukaho/surgeflow-starter-kit/blob/main/notebooks/surgeflow-realtime-hotlist-60s.ipynb

The workbook includes:

- `Start Here` release notes
- `Dashboard` summary view, which reads `Surgeflow_US`
- `Surgeflow_US` sample output in the Google Sheets add-on layout: a
  three-row block (`section`, `market_status`, `market_quality`) above the
  hotlist and above the realtime table. The wrapper also writes `as_of_local`,
  `as_of_utc` and `stale_reason` in columns C:D of each block. The sample
  leaves those cells blank.
- `API Quickstart` endpoint map

The authenticated API, the Colab notebooks and the included Sheets wrapper
source support four markets: `us`, `cn`, `jp` and `hk`. The Google Sheets
add-on is still under Google Workspace Marketplace review and cannot be
installed yet. Until then, add the Apps Script source in
[`apps-script/`](../apps-script/README.md) to a Google Sheets copy of the
workbook. [Use it today](../apps-script/README.md#use-it-today) has the steps.
The wrapper uses the keyless `/api/addin` endpoints, so it needs no API key.

Create a free beta key for the API and the Colab notebooks:

https://surgeflows.capital/membership#api-key

The website-hosted workbook is the source of truth during beta so users always
receive the latest template.
