# Changelog

## 0.3.0 - Unreleased

- The monitor spreads each panel's refresh by up to 10% either way, so monitors started at the same moment do not poll in lockstep.

- Replaced the `NotAvailableYet` stubs for technical cohorts and US layoffs with route calls from candidate stock-api release 4.
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
