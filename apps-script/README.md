# Surgeflow for Google Sheets

This is the Google Sheets add-on wrapper for the frozen `/api/addin/*`
spreadsheet data contract.

Copy all three files into the Apps Script project:

- `appsscript.json`
- `Code.gs`
- `Sidebar.html`

## What it does

- Adds a `Surgeflow` menu and sidebar in Google Sheets.
- Lets the user choose `US`, `CN`, `JP`, `HK`, `TW`, `KR`, `UK`, or `IN`.
- Writes one sheet per market, for example `Surgeflow_US`.
- Writes the hotlist and realtime turnover table into the same sheet.
- Writes values only; no formulas; no portfolio or brokerage access.

## Market boundary

The wrapper, authenticated API, and Colab notebook support eight markets:
`US`, `CN`, `JP`, `HK`, `TW`, `KR`, `UK`, and `IN`. The wrapper reads the
frozen `/api/addin/realtime` and `/api/addin/hotlist` contracts; it does not
infer missing values inside the spreadsheet.

## Scopes

The add-on requests the narrowest practical scopes:

- `https://www.googleapis.com/auth/spreadsheets.currentonly`
- `https://www.googleapis.com/auth/script.external_request`

It does not request Google Drive file-list access.

## Submission state

This source is the eight-market candidate for the next Apps Script deployment.
The Marketplace listing remains in Google authentication and review, so public
one-click installation is not yet available. The owner must synchronize this
source to the linked Apps Script project before approval or resubmission.
