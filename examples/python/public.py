import io

import requests

BASE_URL = "https://surgeflows.capital"
HEADERS = {"User-Agent": "surgeflow-starter-kit-python/0.1.0"}


def get(path):
    response = requests.get(
        f"{BASE_URL}{path}",
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response


freshness_response = get("/api/public/snapshots/data-freshness.json")
freshness = freshness_response.json()
if freshness.get("ok") is False:
    raise RuntimeError("The data-freshness response contains ok=false")
freshness_data = freshness["data"]
print(
    "Public snapshot:",
    freshness["snapshot"],
    "status=" + freshness_data["status"],
    "markets=" + str(len(freshness_data["rows"])),
    "generated_at=" + freshness["generated_at"],
)

hotlist_response = get("/api/public/snapshots/momentum-hotlist.json?market=us")
hotlist = hotlist_response.json()
if hotlist.get("ok") is False:
    raise RuntimeError("The Hotlist response contains ok=false")
hotlist_data = hotlist["data"]
print(
    "Hotlist:",
    "market=us",
    "rows=" + str(len(hotlist_data["rows"])),
    "total_count=" + str(hotlist_data["total_count"]),
    "truncated=" + str(hotlist_data["truncated"]),
    "as_of=" + hotlist_data["as_of"],
)

csv_response = get("/api/public/snapshots/momentum-hotlist.csv?market=us")
csv_text = csv_response.text
try:
    import pandas as pd
except ImportError:
    print("CSV: pandas is not installed; received", len(csv_text.splitlines()) - 1, "rows")
else:
    frame = pd.read_csv(io.StringIO(csv_text))
    print("CSV to pandas:", "rows=" + str(len(frame)), "columns=" + ",".join(frame.columns))
