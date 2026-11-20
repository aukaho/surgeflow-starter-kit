# SurgeFlow Excel add-in

This add-in is not yet in its store. Sideload it for testing in Excel on the web.

Manifest URL:

```text
https://surgeflows.capital/addins/excel/manifest.xml
```

The SurgeFlow site serves the panel files. This folder intentionally excludes those hosted files.

## Sideload in Excel on the web

1. Download the manifest URL as a local file named `manifest.xml`.
2. Open a workbook in Excel on the web.
3. Select **Home → Add-ins → More Add-ins → Upload My Add-in**.
4. Select the downloaded `manifest.xml` file.
5. Open the SurgeFlow task pane from the add-in controls.

This cURL command downloads the manifest:

```bash
curl --fail --silent --show-error \
  "https://surgeflows.capital/addins/excel/manifest.xml" \
  --output manifest.xml
```

The add-in shows only SurgeFlow tickers and SurgeFlow ranks, data freshness, and official open-licence macro statistics with credits. These official statistics can include economies beyond the four equity markets (for example the United Kingdom, Taiwan, and World Bank country series), each with its publisher credit.
It shows no prices, returns, or company names.

Research data only, not investment advice. Market data can be delayed.
Free access does not grant redistribution rights.
