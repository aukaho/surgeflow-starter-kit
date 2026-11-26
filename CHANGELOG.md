# Changelog

## 0.4.1 - 2026-11-26

- Notebook 01 now compares measured index-voter hit rates with the always-up base rate at both supported horizons.
- The index-voter tables explain that no edge is demonstrated and show explicit text for unavailable metrics and absent down calls.
- Updated the Python package and user agent to 0.4.1.

## 0.4.0 - 2026-11-26

- Added shared cohort analytics rows with explicit metric statuses and formatting for notebook 03.
- Analytics rows name each cohort's market and the benchmark the feed reports, and list the longest observation windows first.
- Added cohort window coverage, metric status counts, and available-value medians to the existing monitor panels without extra requests.
- Added fixture coverage for all metric statuses, older cohorts without analytics, unknown fields, and carried risk-free rates.
- Updated the Python package and user agent to 0.4.0.

## 0.3.0 - 2026-11-24

- The monitor delays each panel's refresh by 0 to 10%, never less than its cadence, so monitors started at the same moment do not poll in lockstep.
- Replaced the `NotAvailableYet` stubs for technical cohorts and US layoffs with calls to the live member routes.
- Changed (breaking): `member_technical_cohorts` now takes `market` first, as `member_technical_cohorts(market, api_key)`.
- Added a distinct `SurgeFlowFeedUnavailable` state for the two HTTP 503 feed responses.
- Replaced notebooks 03 and 09 with one-fetch feed tables, source metadata, and plain column guides.
- Added US cohort and layoff monitor panels with six-hour cadence and opt-in cohort markets.
- Updated the default monitor projection to 1,234 scheduled requests plus one startup account check.
- Documented the factor overview as a frozen baseline and linked the keyless daily factor route.
- Updated the Python package and user agent to 0.3.0.

## 0.2.0 - 2026-11-21

- Added Python member methods for the seven key-reachable offerings.
- Added explicit `NotAvailableYet` stubs for Technical cohorts and Layoffs.
- Added the scheduled monitor with a 1,500-request default budget and session gates.
- Added eleven cleared-output notebooks with synthetic fixtures and offline execution tests.
- Added catalogue-based base URLs, `Retry-After` handling, and change highlighting.
- Documented source dates, quota use, and the redistribution boundary.
- Member portfolios (offering 06) read `GET /api/portfolio`; an empty account shows "No portfolios yet".
- Python and JavaScript clients show the API's error code and message.
- Member research routes are labelled beta until they appear in `/api/v1/catalog`.

## 0.1.0 - 2026-11-20

- Rebuilt the starter kit around the current four-market SurgeFlow API.
- Added no-key cURL, Python, JavaScript, and Google Sheets examples.
- Added local Python and JavaScript client packages with offline tests.
- Added Google Sheets, Excel, and Chrome app distribution sources.
- Replaced the old quickstart with one current Markdown guide.
- Removed the eight-market add-on, notebook, and outdated template references.
- Added repository contribution and release notes.

Public data is research data only. Free access does not grant redistribution rights.
