# Surgeflow for Google Sheets

This is the Google Sheets add-on wrapper for the frozen `/api/addin/*`
spreadsheet data contract.

Copy all three files into the Apps Script project:

- `appsscript.json`
- `Code.gs`
- `Sidebar.html`

## What it does

- Adds a `Surgeflow` menu and sidebar in Google Sheets.
- Lets the user choose `US`, `CN`, `JP`, `HK`, `UK`, or `IN`.
- Writes one sheet per market, for example `Surgeflow_US`.
- Writes the hotlist and realtime turnover table into the same sheet.
- Writes values only; no formulas; no portfolio or brokerage access.

## Scopes

The add-on requests the narrowest practical scopes:

- `https://www.googleapis.com/auth/spreadsheets.currentonly`
- `https://www.googleapis.com/auth/script.external_request`

It does not request Google Drive file-list access.

## Submission state

This source mirrors the Surgeflow for Google Sheets add-on submitted for Google
authentication and Workspace Marketplace review. Public one-click installation
will be available after Google approval.
