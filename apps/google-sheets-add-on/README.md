# SurgeFlow Google Sheets add-on

This add-on inserts no-key public SurgeFlow snapshots into new sheets.
It is not yet in the Google Workspace Marketplace. Install this source as a bound script.

## Install as a bound script

1. Create or open a Google Sheets spreadsheet.
2. Select **Extensions → Apps Script** to create a bound script.
3. Copy `Code.gs` and `Config.gs` into script files with those names.
4. Create an HTML file named `Sidebar` and copy `Sidebar.html` into it.
5. Open **Project Settings** and enable the `appsscript.json` manifest display.
6. Copy `appsscript.json` into the manifest editor and save the project.
7. Reload the spreadsheet and open the **SurgeFlow** menu.
8. Authorize the declared spreadsheet, interface, and external-request scopes when Google prompts you.

Select **Insert data…** from the SurgeFlow menu.
Choose one of the four markets when the selected snapshot needs a market.

The add-on shows only SurgeFlow tickers and SurgeFlow ranks, data freshness, and official open-licence macro statistics with credits. These official statistics can include economies beyond the four equity markets (for example the United Kingdom, Taiwan, and World Bank country series), each with its publisher credit.
It shows no prices, returns, or company names.
It needs no SurgeFlow sign-in or API key.

Research data only, not investment advice. Market data can be delayed.
Free access does not grant redistribution rights.
