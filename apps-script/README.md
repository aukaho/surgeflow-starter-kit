# Surgeflow for Google Sheets

This is the Google Sheets add-on wrapper for the frozen `/api/addin/*`
spreadsheet data contract.

Copy all three files into the Apps Script project:

- `appsscript.json`
- `Code.gs`
- `Sidebar.html`

## What it does

- Adds a `Surgeflow` menu and sidebar in Google Sheets.
- Lets the user choose `US`, `CN`, `JP` or `HK`.
- Writes one sheet per market, for example `Surgeflow_US`.
- Writes the hotlist and realtime turnover table (up to 100 rows, the
  documented maximum `limit`) into the same sheet.
- Writes freshness rows above each table: `market_status`, `data_quality`,
  `stale_reason`, `as_of_local` and `as_of_utc`. A closed market returns its
  last session, so check the as-of time before you read the numbers.
- Leaves the hotlist with headers only when it has no names
  (`data_quality: empty`). The `stale_reason` row above the headers says why,
  for example `no_current_hotlist_members`. An empty hotlist is normal, not an
  error.
- Writes values only; no formulas; no portfolio or brokerage access.

## Market boundary

The wrapper, the authenticated API and the Colab notebooks support four
markets: `US`, `CN`, `JP` and `HK`. The wrapper reads the frozen, keyless
`/api/addin/realtime` and `/api/addin/hotlist` contracts. It does not infer
missing values inside the spreadsheet.

## Scopes

The add-on requests the narrowest practical scopes:

- `https://www.googleapis.com/auth/spreadsheets.currentonly`
- `https://www.googleapis.com/auth/script.external_request`

It does not request Google Drive file-list access.

## Submission state

This source is the four-market candidate for the next Apps Script deployment.
The Marketplace listing remains in Google authentication and review, so public
one-click installation is not yet available. Before approval or resubmission,
the owner must synchronize this source into the linked Apps Script project and
re-run the four-market contract test.

The four-market contract test is a manual check, not a script in this
repository:

1. Copy the three files into the Apps Script project bound to a copy of the
   starter workbook.
2. Run **Refresh US**, **Refresh CN**, **Refresh JP** and **Refresh HK** from
   the `Surgeflow` menu.
3. Confirm that each run writes its `Surgeflow_{MARKET}` sheet without an
   error, that the realtime section lists rows (the wrapper asks for
   `limit=100`), that both sections show their freshness rows, and that an
   empty hotlist shows `data_quality: empty` with headers only.
