# Surgeflow for Google Sheets

This is the Google Sheets add-on wrapper for the frozen `/api/addin/*`
spreadsheet data contract. It has three files: `appsscript.json` (the
manifest, which sets the OAuth scopes), `Code.gs` and `Sidebar.html`.

No API key is needed. The wrapper uses the keyless `/api/addin/realtime` and
`/api/addin/hotlist` endpoints, not the key-gated `/api/v1` API.

## Use it today

The add-on is still in Google review, so you cannot install it from the
Google Workspace Marketplace yet. Until then, run the same source in your own
copy of the starter workbook:

1. Download the
   [starter workbook](https://surgeflows.capital/templates/surgeflow-google-sheets-starter.xlsx),
   upload it to Google Drive, open it with Google Sheets and choose
   **File > Save as Google Sheets**. Apps Script needs a Google Sheets file,
   not an `.xlsx` file.
2. In that Google Sheets copy, open **Extensions > Apps Script**.
3. Open **Project Settings** (the gear icon) and tick
   **Show "appsscript.json" manifest file in editor**. The editor hides the
   manifest by default. Without it, the two narrow scopes listed under
   [Scopes](#scopes) are not applied, and Apps Script asks for the broader
   scopes it detects by itself.
4. Go back to the **Editor**. Replace the contents of `appsscript.json` and
   `Code.gs` with the files from this folder. Add an HTML file named `Sidebar`
   (the editor adds `.html`) and paste in `Sidebar.html`.
5. Click **Save project**, then reload the spreadsheet tab. A `Surgeflow`
   menu appears.
6. Choose **Surgeflow > Refresh US** (or another market). The first run asks
   you to authorize the script. Check that it asks only for the two scopes
   listed under [Scopes](#scopes): manage this spreadsheet, and connect to an
   external service. Then allow it. Because this is your own copy, Google may
   first say that it has not verified the app. Choose **Advanced** and
   continue to your project.

## What it does

- Adds a `Surgeflow` menu and sidebar in Google Sheets.
- Lets the user choose `US`, `CN`, `JP` or `HK`.
- Writes one sheet per market, for example `Surgeflow_US`.
- Writes the hotlist and the realtime turnover table into the same sheet.
- Writes a three-row freshness block above each table. Columns A:B hold
  `section`, `market_status` and `market_quality` (the API's `data_quality`).
  Columns C:D hold `as_of_local`, `as_of_utc` and `stale_reason`. A closed
  market returns its last session, so check the as-of time before you read
  the numbers.
- Leaves the hotlist with headers only when it has no names. `market_quality`
  then shows `empty`, and the `stale_reason` cell next to it says why, for
  example `no_current_hotlist_members`. An empty hotlist is normal, not an
  error.
- Writes values only; no formulas; no portfolio or brokerage access.

## Sheet layout

Keep the layout of the A:B columns fixed. The starter workbook's `Dashboard`
reads `Surgeflow_US` in two ways. It finds `market_status` and
`market_quality` by those labels in column A. It also takes the first realtime
row from 5 rows below the `REALTIME TABLE` cell. Renaming those labels, or
adding rows to the freshness block, breaks the Dashboard. Add new fields in
columns C:D instead.

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

1. Set up a Google Sheets copy of the starter workbook with this source, as
   in [Use it today](#use-it-today), steps 1 to 5.
2. Run **Refresh US**, **Refresh CN**, **Refresh JP** and **Refresh HK** from
   the `Surgeflow` menu. Then open **Surgeflow > Open** and refresh one market
   from the sidebar.
3. Confirm that each run writes its `Surgeflow_{MARKET}` sheet without an
   error and that the realtime section lists rows. Confirm that both sections
   show the freshness block (`market_status`, `market_quality`, `as_of_local`,
   `as_of_utc` and `stale_reason`). Confirm that an empty hotlist shows
   `market_quality` `empty` with headers only.
4. Run **Refresh US** last, then open `Dashboard`. It reads `Surgeflow_US`
   only. Confirm that **Top ticker** shows the first ticker of the realtime
   table (not a timestamp or a blank). Confirm that **Market status** and
   **Data quality** show the values from the sheet, and that the table below
   them lists the first realtime rows.
