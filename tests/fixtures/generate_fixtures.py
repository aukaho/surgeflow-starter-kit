#!/usr/bin/env python3
"""Build the synthetic offline fixtures served by tools/mock_api.py.

    python tests/fixtures/generate_fixtures.py           # (re)write every fixture
    python tests/fixtures/generate_fixtures.py --check   # exit 1 if any fixture is stale

The payload STRUCTURE mirrors real authenticated v1 responses captured on
2026-10-07 (tests/fixtures/live/, git-ignored): the same key paths, nesting,
types, enum vocabularies and value ranges. Every VALUE is synthetic: no
price, score or comment is copied from a live response, free text (notes,
analyst comments, headlines, rationales) is a neutral placeholder sentence,
and account fields are fake. tests/fixtures/README.md documents each field and
how sure we are of it. catalog.json and health.json are real responses and are
never touched.

Two endpoints errored live on 2026-10-07 (news: an upstream error inside a 200;
summary: HTTP 500), so their payloads keep an INFERRED shape.

Design:
- One ticker universe per market (real tickers for the largest names, then
  synthetic tickers and names) is shared by screen, sector, realtime, hotlist,
  whales, ml/clusters, factor holdings, news and notes, so notebooks can join on
  ticker. ai/ratings and ai/grade-book use the US universe.
- Tickers carry latent styles (momentum, volatility, quality, value, growth,
  attention, size, leverage) drawn around a few archetypes. Screen columns are
  noisy readings of those latents, ml/clusters labels come from the latents, so
  k-means on screen columns recovers SurgeFlow's clusters only partly.
- The daily change is only weakly related to the other screen columns.
- Deterministic: every component draws from numpy.random.default_rng seeded with
  SEED plus the component name. Standard library + numpy only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zlib
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
SEED = 20261007
MARKETS = ("us", "cn", "jp", "hk")
NOW = datetime(2026, 10, 7, 5, 20, tzinfo=timezone.utc)  # fixture wall clock (live probe: ~05:25 UTC)
TODAY = NOW.date()
PAGE_SIZE = 100  # the screen's maximum page size
SCREEN_PAGES = 3  # largest-cap pages written per market; tools/mock_api.py empties later pages
REAL_FIXTURES = ("catalog.json", "health.json")  # real responses: never generated
NOTE = "Automated research documentation; not investment advice or a solicitation."
SITE = "https://surgeflows.capital"


# ---------------------------------------------------------------------------- helpers
def rng_for(*keys) -> np.random.Generator:
    return np.random.default_rng([SEED, *(zlib.crc32(str(k).encode()) for k in keys)])


def num(x, nd=4):
    """Rounded float, or None for missing / non-finite values."""
    if x is None:
        return None
    x = float(x)
    return round(x, nd) + 0.0 if math.isfinite(x) else None  # + 0.0 turns -0.0 into 0.0


def money(x):
    """Whole currency units as a float (1234.0), the way the live payloads print them."""
    if x is None:
        return None
    x = float(x)
    return float(round(x)) if math.isfinite(x) else None


def clean(obj):
    """numpy scalars -> plain Python; NaN -> None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, np.str_):
        return str(obj)
    return obj


def hexid(*parts, n=32) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:n]


def md5id(*parts) -> str:
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()


def utc(y, mo, d, h=0, mi=0, s=0, us=0) -> datetime:
    return datetime(y, mo, d, h, mi, s, us, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def local_iso(dt: datetime, offset_hours: int) -> str:
    return dt.astimezone(timezone(timedelta(hours=offset_hours))).isoformat()


def stamp(rng, base: datetime, max_minutes: float = 30.0) -> str:
    """A microsecond timestamp a little after base (live timestamps carry microseconds)."""
    return iso(base + timedelta(seconds=float(rng.uniform(0, 60 * max_minutes)),
                                microseconds=int(rng.integers(1, 999999))))


def rank_pct(values) -> np.ndarray:
    """0 for the smallest value, 1 for the largest (stable ties)."""
    values = np.asarray(values, float)
    order = np.argsort(np.argsort(values, kind="stable"), kind="stable")
    return order / max(len(values) - 1, 1)


def zs(x) -> np.ndarray:
    x = np.asarray(x, float)
    sd = x.std()
    return (x - x.mean()) / (sd if sd > 0 else 1.0)


def group_wmean(keys, values, weights, min_members: int = 1) -> np.ndarray:
    """Weighted mean of values within each key, mapped back to every row (None keys and groups with fewer
    than min_members rows -> NaN)."""
    keys = list(keys)
    out = np.full(len(keys), np.nan)
    for key in dict.fromkeys(keys):
        if key is None:
            continue
        idx = np.array([i for i, k in enumerate(keys) if k == key])
        if len(idx) < min_members:
            continue
        v, w = values[idx], weights[idx]
        ok = np.isfinite(v)
        if ok.any():
            out[idx] = float(np.sum(v[ok] * w[ok]) / np.sum(w[ok]))
    return out


# ---------------------------------------------------------------------------- calendar
HOLIDAYS = {
    "us": {date(2026, 7, 3), date(2026, 9, 7)},
    "cn": {date(2026, 10, d) for d in range(1, 9)},  # Golden Week: the live CN board stays on 2026-09-30
    "jp": {date(2026, 7, 20), date(2026, 8, 11), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)},
    "hk": {date(2026, 7, 1), date(2026, 10, 1)},
}


def is_trading(m: str, day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS[m]


def trading_days(m: str, end: date, n: int) -> list[date]:
    """The n trading days ending at (and including) end."""
    out, cur = [], end
    while len(out) < n:
        if is_trading(m, cur):
            out.append(cur)
        cur -= timedelta(days=1)
    return out[::-1]


def trading_between(m: str, start: date, end: date) -> list[date]:
    out, cur = [], start
    while cur <= end:
        if is_trading(m, cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def prev_trading(m: str, day: date, k: int = 1) -> date:
    cur = day
    while k:
        cur -= timedelta(days=1)
        if is_trading(m, cur):
            k -= 1
    return cur


# ---------------------------------------------------------------------------- vocabularies (from live responses)
SECTORS = ["Technology", "Healthcare", "Financial Services", "Consumer Cyclical", "Consumer Defensive",
           "Industrials", "Energy", "Basic Materials", "Real Estate", "Utilities", "Communication Services"]
UNCLASSIFIED = "Unclassified"  # live sector label for unmapped listings (industry is then null)
INDUSTRIES = {
    "Technology": ["Semiconductors", "Software - Application", "Software - Infrastructure", "Hardware, Equipment & Parts",
                   "Communication Equipment", "Information Technology Services", "Computer Hardware",
                   "Consumer Electronics", "Electrical Equipment & Parts", "Technology Distributors"],
    "Healthcare": ["Biotechnology", "Drug Manufacturers - Specialty & Generic", "Drug Manufacturers - General",
                   "Medical - Devices", "Medical - Instruments & Supplies", "Medical - Care Facilities",
                   "Medical - Diagnostics & Research", "Medical - Healthcare Information Services",
                   "Medical - Distribution", "Medical - Healthcare Plans"],
    "Financial Services": ["Banks - Regional", "Banks - Diversified", "Asset Management", "Financial - Capital Markets",
                           "Financial - Credit Services", "Insurance - Property & Casualty", "Insurance - Life",
                           "Insurance - Diversified", "Financial - Conglomerates", "Financial - Data & Stock Exchanges"],
    "Consumer Cyclical": ["Auto - Parts", "Auto - Manufacturers", "Specialty Retail", "Restaurants",
                          "Apparel - Manufacturers", "Apparel - Retail", "Furnishings, Fixtures & Appliances",
                          "Leisure", "Luxury Goods", "Apparel - Footwear & Accessories", "Department Stores"],
    "Consumer Defensive": ["Packaged Foods", "Agricultural Farm Products", "Household & Personal Products",
                           "Beverages - Non-Alcoholic", "Beverages - Wineries & Distilleries", "Beverages - Alcoholic",
                           "Food Distribution", "Grocery Stores", "Discount Stores", "Food Confectioners"],
    "Industrials": ["Industrial - Machinery", "Engineering & Construction", "Electrical Equipment & Parts",
                    "Specialty Business Services", "Aerospace & Defense", "Conglomerates",
                    "Integrated Freight & Logistics", "Marine Shipping", "Manufacturing - Metal Fabrication",
                    "Staffing & Employment Services", "Railroads"],
    "Energy": ["Oil & Gas Exploration & Production", "Oil & Gas Equipment & Services", "Oil & Gas Integrated",
               "Oil & Gas Midstream", "Oil & Gas Refining & Marketing", "Coal", "Solar", "Uranium"],
    "Basic Materials": ["Chemicals - Specialty", "Chemicals", "Steel", "Industrial Materials", "Construction Materials",
                        "Agricultural Inputs", "Aluminum", "Gold", "Copper", "Paper, Lumber & Forest Products"],
    "Real Estate": ["Real Estate - Development", "Real Estate - Services", "Real Estate - Diversified", "REIT - Retail",
                    "REIT - Industrial", "REIT - Office", "REIT - Residential", "REIT - Mortgage",
                    "REIT - Healthcare Facilities", "REIT - Specialty"],
    "Utilities": ["Regulated Electric", "Renewable Utilities", "Regulated Gas", "Independent Power Producers",
                  "Regulated Water", "Diversified Utilities"],
    "Communication Services": ["Internet Content & Information", "Telecommunications Services", "Entertainment",
                               "Electronic Gaming & Multimedia", "Advertising Agencies", "Broadcasting", "Publishing"],
}
SECTOR_WEIGHTS = {  # share of each sector in the synthetic universe (order of SECTORS)
    "us": [14, 18, 19, 9, 4, 14, 5, 5, 6, 3, 4],
    "cn": [18, 10, 3, 16, 4, 30, 2, 13, 2, 3, 1],
    "jp": [8, 2, 5, 12, 4, 39, 1, 10, 4, 1, 15],
    "hk": [13, 12, 8, 16, 7, 20, 3, 6, 7, 3, 5],
}
RARE_INDUSTRIES = {  # live: one-member industries get industry_mean_1d = null
    "Industrials": ["Manufacturing - Miscellaneous", "Industrial - Capital Goods", "Manufacturing - Textiles"],
    "Financial Services": ["Asset Management - Global"],
}
UNCLASSIFIED_SHARE = {"us": 0.0, "cn": 0.002, "jp": 0.013, "hk": 0.005}
INDUSTRY_NULL_SHARE = {"us": 0.0, "cn": 0.14, "jp": 0.02, "hk": 0.01}  # classified rows with a null industry

# Real tickers and names for the largest listings. Every number attached to them is synthetic.
ANCHORS = {
    "us": [
        ("NVDA", "NVIDIA Corporation", "Technology", "Semiconductors"),
        ("MSFT", "Microsoft Corporation", "Technology", "Software - Infrastructure"),
        ("AAPL", "Apple Inc.", "Technology", "Consumer Electronics"),
        ("AMZN", "Amazon.com, Inc.", "Consumer Cyclical", "Specialty Retail"),
        ("GOOGL", "Alphabet Inc.", "Communication Services", "Internet Content & Information"),
        ("META", "Meta Platforms, Inc.", "Communication Services", "Internet Content & Information"),
        ("AVGO", "Broadcom Inc.", "Technology", "Semiconductors"),
        ("TSLA", "Tesla, Inc.", "Consumer Cyclical", "Auto - Manufacturers"),
        ("BRK-B", "Berkshire Hathaway Inc.", "Financial Services", "Insurance - Diversified"),
        ("JPM", "JPMorgan Chase & Co.", "Financial Services", "Banks - Diversified"),
        ("LLY", "Eli Lilly and Company", "Healthcare", "Drug Manufacturers - General"),
        ("V", "Visa Inc.", "Financial Services", "Financial - Credit Services"),
        ("WMT", "Walmart Inc.", "Consumer Defensive", "Discount Stores"),
        ("ORCL", "Oracle Corporation", "Technology", "Software - Infrastructure"),
        ("MA", "Mastercard Incorporated", "Financial Services", "Financial - Credit Services"),
        ("XOM", "Exxon Mobil Corporation", "Energy", "Oil & Gas Integrated"),
        ("COST", "Costco Wholesale Corporation", "Consumer Defensive", "Discount Stores"),
        ("NFLX", "Netflix, Inc.", "Communication Services", "Entertainment"),
        ("PG", "The Procter & Gamble Company", "Consumer Defensive", "Household & Personal Products"),
        ("HD", "The Home Depot, Inc.", "Consumer Cyclical", "Specialty Retail"),
        ("AMD", "Advanced Micro Devices, Inc.", "Technology", "Semiconductors"),
        ("BAC", "Bank of America Corporation", "Financial Services", "Banks - Diversified"),
        ("ABBV", "AbbVie Inc.", "Healthcare", "Drug Manufacturers - General"),
        ("PLTR", "Palantir Technologies Inc.", "Technology", "Software - Infrastructure"),
        ("KO", "The Coca-Cola Company", "Consumer Defensive", "Beverages - Non-Alcoholic"),
        ("MU", "Micron Technology, Inc.", "Technology", "Semiconductors"),
        ("CVX", "Chevron Corporation", "Energy", "Oil & Gas Integrated"),
        ("UNH", "UnitedHealth Group Incorporated", "Healthcare", "Medical - Healthcare Plans"),
        ("GS", "The Goldman Sachs Group, Inc.", "Financial Services", "Financial - Capital Markets"),
        ("CRM", "Salesforce, Inc.", "Technology", "Software - Application"),
        ("GE", "GE Aerospace", "Industrials", "Aerospace & Defense"),
        ("CAT", "Caterpillar Inc.", "Industrials", "Industrial - Machinery"),
        ("MRK", "Merck & Co., Inc.", "Healthcare", "Drug Manufacturers - General"),
        ("INTC", "Intel Corporation", "Technology", "Semiconductors"),
        ("TMO", "Thermo Fisher Scientific Inc.", "Healthcare", "Medical - Diagnostics & Research"),
        ("LIN", "Linde plc", "Basic Materials", "Chemicals - Specialty"),
        ("ISRG", "Intuitive Surgical, Inc.", "Healthcare", "Medical - Instruments & Supplies"),
        ("DIS", "The Walt Disney Company", "Communication Services", "Entertainment"),
        ("QCOM", "QUALCOMM Incorporated", "Technology", "Semiconductors"),
        ("T", "AT&T Inc.", "Communication Services", "Telecommunications Services"),
        ("VZ", "Verizon Communications Inc.", "Communication Services", "Telecommunications Services"),
        ("ADBE", "Adobe Inc.", "Technology", "Software - Application"),
        ("BA", "The Boeing Company", "Industrials", "Aerospace & Defense"),
        ("NEE", "NextEra Energy, Inc.", "Utilities", "Regulated Electric"),
        ("PFE", "Pfizer Inc.", "Healthcare", "Drug Manufacturers - General"),
        ("MRVL", "Marvell Technology, Inc.", "Technology", "Semiconductors"),
        ("HON", "Honeywell International Inc.", "Industrials", "Conglomerates"),
        ("DE", "Deere & Company", "Industrials", "Industrial - Machinery"),
        ("PLD", "Prologis, Inc.", "Real Estate", "REIT - Industrial"),
        ("MCD", "McDonald's Corporation", "Consumer Cyclical", "Restaurants"),
        ("COIN", "Coinbase Global, Inc.", "Financial Services", "Financial - Capital Markets"),
        ("UPS", "United Parcel Service, Inc.", "Industrials", "Integrated Freight & Logistics"),
        ("FCX", "Freeport-McMoRan Inc.", "Basic Materials", "Copper"),
        ("NEM", "Newmont Corporation", "Basic Materials", "Gold"),
        ("AMT", "American Tower Corporation", "Real Estate", "REIT - Specialty"),
        ("DUK", "Duke Energy Corporation", "Utilities", "Regulated Electric"),
        ("NKE", "NIKE, Inc.", "Consumer Cyclical", "Apparel - Footwear & Accessories"),
        ("SBUX", "Starbucks Corporation", "Consumer Cyclical", "Restaurants"),
        ("DVN", "Devon Energy Corporation", "Energy", "Oil & Gas Exploration & Production"),
        ("O", "Realty Income Corporation", "Real Estate", "REIT - Retail"),
    ],
    "cn": [
        ("601398", "工商银行", "Financial Services", "Banks - Diversified"),
        ("600519", "贵州茅台", "Consumer Defensive", "Beverages - Wineries & Distilleries"),
        ("300750", "宁德时代", "Industrials", "Electrical Equipment & Parts"),
        ("601288", "农业银行", "Financial Services", "Banks - Diversified"),
        ("601939", "建设银行", "Financial Services", "Banks - Diversified"),
        ("601318", "中国平安", "Financial Services", "Insurance - Life"),
        ("600036", "招商银行", "Financial Services", "Banks - Regional"),
        ("688981", "中芯国际", "Technology", "Semiconductors"),
        ("601857", "中国石油", "Energy", "Oil & Gas Integrated"),
        ("600900", "长江电力", "Utilities", "Renewable Utilities"),
        ("002594", "比亚迪", "Consumer Cyclical", "Auto - Manufacturers"),
        ("300308", "中际旭创", "Technology", "Communication Equipment"),
        ("601899", "紫金矿业", "Basic Materials", "Gold"),
        ("000858", "五粮液", "Consumer Defensive", "Beverages - Wineries & Distilleries"),
        ("601088", "中国神华", "Energy", "Coal"),
        ("000333", "美的集团", "Consumer Cyclical", "Furnishings, Fixtures & Appliances"),
        ("600030", "中信证券", "Financial Services", "Financial - Capital Markets"),
        ("300502", "新易盛", "Technology", "Communication Equipment"),
        ("601728", "中国电信", "Communication Services", "Telecommunications Services"),
        ("688041", "海光信息", "Technology", "Semiconductors"),
        ("600276", "恒瑞医药", "Healthcare", "Drug Manufacturers - Specialty & Generic"),
        ("002475", "立讯精密", "Technology", "Hardware, Equipment & Parts"),
        ("600028", "中国石化", "Energy", "Oil & Gas Integrated"),
        ("300059", "东方财富", "Financial Services", "Financial - Capital Markets"),
        ("000651", "格力电器", "Consumer Cyclical", "Furnishings, Fixtures & Appliances"),
        ("600309", "万华化学", "Basic Materials", "Chemicals"),
        ("600887", "伊利股份", "Consumer Defensive", "Packaged Foods"),
        ("300274", "阳光电源", "Industrials", "Electrical Equipment & Parts"),
        ("002415", "海康威视", "Technology", "Hardware, Equipment & Parts"),
        ("000001", "平安银行", "Financial Services", "Banks - Regional"),
        ("601012", "隆基绿能", "Technology", "Semiconductors"),
        ("600048", "保利发展", "Real Estate", "Real Estate - Development"),
        ("600016", "民生银行", "Financial Services", "Banks - Regional"),
        ("002230", "科大讯飞", "Technology", "Software - Application"),
    ],
    "jp": [
        ("7203", "TOYOTA MOTOR CORPORATION", "Consumer Cyclical", "Auto - Manufacturers"),
        ("8306", "Mitsubishi UFJ Financial Group,Inc.", "Financial Services", "Banks - Diversified"),
        ("6758", "Sony Group Corporation", "Technology", "Consumer Electronics"),
        ("6857", "ADVANTEST CORPORATION", "Technology", "Semiconductors"),
        ("6501", "Hitachi,Ltd.", "Industrials", "Conglomerates"),
        ("9983", "FAST RETAILING CO.,LTD.", "Consumer Cyclical", "Apparel - Retail"),
        ("9984", "SoftBank Group Corp.", "Communication Services", "Telecommunications Services"),
        ("8035", "Tokyo Electron Limited", "Technology", "Semiconductors"),
        ("8316", "Sumitomo Mitsui Financial Group,Inc.", "Financial Services", "Banks - Diversified"),
        ("7974", "Nintendo Co.,Ltd.", "Communication Services", "Electronic Gaming & Multimedia"),
        ("6861", "KEYENCE CORPORATION", "Technology", "Hardware, Equipment & Parts"),
        ("8058", "Mitsubishi Corporation", "Industrials", "Conglomerates"),
        ("8001", "ITOCHU Corporation", "Industrials", "Conglomerates"),
        ("9432", "NIPPON TELEGRAPH AND TELEPHONE CORPORATION", "Communication Services", "Telecommunications Services"),
        ("4063", "Shin-Etsu Chemical Co.,Ltd.", "Basic Materials", "Chemicals - Specialty"),
        ("8411", "Mizuho Financial Group,Inc.", "Financial Services", "Banks - Diversified"),
        ("7011", "Mitsubishi Heavy Industries,Ltd.", "Industrials", "Industrial - Machinery"),
        ("8031", "MITSUI & CO.,LTD.", "Industrials", "Conglomerates"),
        ("6098", "Recruit Holdings Co.,Ltd.", "Industrials", "Staffing & Employment Services"),
        ("9433", "KDDI CORPORATION", "Communication Services", "Telecommunications Services"),
        ("4502", "Takeda Pharmaceutical Company Limited", "Healthcare", "Drug Manufacturers - General"),
        ("8766", "Tokio Marine Holdings,Inc.", "Financial Services", "Insurance - Property & Casualty"),
        ("7267", "Honda Motor Co.,Ltd.", "Consumer Cyclical", "Auto - Manufacturers"),
        ("4519", "CHUGAI PHARMACEUTICAL CO.,LTD.", "Healthcare", "Drug Manufacturers - General"),
        ("6367", "DAIKIN INDUSTRIES,LTD.", "Industrials", "Industrial - Machinery"),
        ("285A", "Kioxia Holdings Corporation", "Technology", "Semiconductors"),
        ("6902", "DENSO CORPORATION", "Consumer Cyclical", "Auto - Parts"),
        ("4568", "DAIICHI SANKYO COMPANY,LIMITED", "Healthcare", "Drug Manufacturers - General"),
        ("6146", "DISCO CORPORATION", "Technology", "Semiconductors"),
        ("8801", "Mitsui Fudosan Co.,Ltd.", "Real Estate", "Real Estate - Diversified"),
        ("2914", "JAPAN TOBACCO INC.", "Consumer Defensive", "Agricultural Farm Products"),
        ("5401", "NIPPON STEEL CORPORATION", "Basic Materials", "Steel"),
        ("1605", "INPEX CORPORATION", "Energy", "Oil & Gas Exploration & Production"),
        ("9501", "Tokyo Electric Power Company Holdings,Incorporated", "Utilities", "Regulated Electric"),
        ("6976", "TAIYO YUDEN CO.,LTD.", "Technology", "Hardware, Equipment & Parts"),
        ("3407", "ASAHI KASEI CORPORATION", "Basic Materials", "Chemicals"),
    ],
    "hk": [
        ("00700", "腾讯控股", "Communication Services", "Internet Content & Information"),
        ("09988", "阿里巴巴-W", "Consumer Cyclical", "Specialty Retail"),
        ("00005", "汇丰控股", "Financial Services", "Banks - Diversified"),
        ("01398", "工商银行", "Financial Services", "Banks - Diversified"),
        ("00939", "建设银行", "Financial Services", "Banks - Diversified"),
        ("01810", "小米集团-W", "Technology", "Consumer Electronics"),
        ("00941", "中国移动", "Communication Services", "Telecommunications Services"),
        ("03690", "美团-W", "Consumer Cyclical", "Specialty Retail"),
        ("01299", "友邦保险", "Financial Services", "Insurance - Life"),
        ("03988", "中国银行", "Financial Services", "Banks - Diversified"),
        ("00883", "中国海洋石油", "Energy", "Oil & Gas Exploration & Production"),
        ("02318", "中国平安", "Financial Services", "Insurance - Life"),
        ("00388", "香港交易所", "Financial Services", "Financial - Data & Stock Exchanges"),
        ("01211", "比亚迪股份", "Consumer Cyclical", "Auto - Manufacturers"),
        ("09618", "京东集团-SW", "Consumer Cyclical", "Specialty Retail"),
        ("09999", "网易-S", "Communication Services", "Electronic Gaming & Multimedia"),
        ("00981", "中芯国际", "Technology", "Semiconductors"),
        ("01024", "快手-W", "Communication Services", "Internet Content & Information"),
        ("00016", "新鸿基地产", "Real Estate", "Real Estate - Development"),
        ("02020", "安踏体育", "Consumer Cyclical", "Apparel - Footwear & Accessories"),
        ("00001", "长和", "Industrials", "Conglomerates"),
        ("00002", "中电控股", "Utilities", "Regulated Electric"),
        ("00027", "银河娱乐", "Consumer Cyclical", "Leisure"),
        ("02269", "药明生物", "Healthcare", "Biotechnology"),
        ("00992", "联想集团", "Technology", "Computer Hardware"),
        ("00003", "香港中华煤气", "Utilities", "Regulated Gas"),
        ("01177", "中国生物制药", "Healthcare", "Drug Manufacturers - Specialty & Generic"),
        ("00669", "创科实业", "Industrials", "Industrial - Machinery"),
        ("02382", "舜宇光学科技", "Technology", "Hardware, Equipment & Parts"),
        ("01093", "石药集团", "Healthcare", "Drug Manufacturers - Specialty & Generic"),
        ("06862", "海底捞", "Consumer Cyclical", "Restaurants"),
        ("01766", "中国中车", "Industrials", "Railroads"),
    ],
}

US_STEMS = ["Alder", "Bluestem", "Cedarline", "Crescent", "Northfield", "Harborview", "Summitry", "Ironwood",
            "Silverline", "Keystone", "Lakeshore", "Meridian", "Pinecrest", "Redwood", "Westbrook", "Brightwater",
            "Clearpath", "Evergreen", "Granite", "Highland", "Juniper", "Maplewood", "Oakmont", "Prairie",
            "Riverbend", "Stonegate", "Tidewater", "Vantage", "Willowby", "Aspenridge", "Beaconfield", "Cobalt",
            "Emberly", "Falconer", "Glacier", "Horizonte", "Jasper", "Kestrel", "Lumenis", "Mosaic", "Nimbus",
            "Orion", "Paragon", "Quarry", "Ridgeline", "Sable", "Trident", "Upland", "Vertexa", "Wavecrest",
            "Zenith", "Arbor", "Bayview", "Copperline", "Driftwood", "Eastgate", "Foxhollow", "Greystone",
            "Hollis", "Ivyline", "Larkspur", "Marrow", "Northstar", "Overbrook", "Palisade", "Quillon", "Rockport",
            "Sundial", "Tamarack", "Ulster", "Valemont", "Whitfield", "Yarrow", "Amberly", "Brookline", "Calloway"]
US_SUFFIX = {
    "Technology": ["Semiconductor Corp.", "Systems, Inc.", "Software, Inc.", "Networks, Inc.", "Photonics, Inc."],
    "Healthcare": ["Therapeutics, Inc.", "Biosciences, Inc.", "Pharmaceuticals, Inc.", "Medical Corp."],
    "Financial Services": ["Bancorp, Inc.", "Financial Corporation", "Capital Group, Inc.", "Bankshares, Inc."],
    "Consumer Cyclical": ["Brands, Inc.", "Retail Group, Inc.", "Motors Corp.", "Restaurants, Inc."],
    "Consumer Defensive": ["Foods, Inc.", "Beverage Co.", "Consumer Products, Inc.", "Farms, Inc."],
    "Industrials": ["Industries, Inc.", "Aerospace Corp.", "Machinery, Inc.", "Logistics, Inc."],
    "Energy": ["Energy, Inc.", "Resources Corp.", "Petroleum Corp.", "Midstream Partners, L.P."],
    "Basic Materials": ["Materials, Inc.", "Chemical Corp.", "Mining Corp.", "Minerals, Inc."],
    "Real Estate": ["Realty Trust, Inc.", "Properties, Inc.", "Residential REIT, Inc."],
    "Utilities": ["Power & Light Co.", "Utilities, Inc.", "Water Co.", "Renewables, Inc."],
    "Communication Services": ["Media, Inc.", "Communications, Inc.", "Interactive, Inc."],
}
JP_STEMS = ["KANTO", "HOKURIKU", "SHINWA", "YAMATO", "TOHOKU", "NISSHO", "KYOWA", "MEIKO", "TOYO", "KITANO",
            "MINAMI", "NISHIKAWA", "HIGASHIYAMA", "TAISEI", "HIKARI", "SAKURA", "MIDORI", "KAEDE", "TSUBASA",
            "CHUBU", "SHIKOKU", "KYUSHU", "SETOUCHI", "HOKKAI", "SANWA", "DAITO", "TOKAI", "NICHIEI", "SUMIDA",
            "ARAKAWA", "FUJIMI", "AOBA", "WAKABA", "KOTOBUKI", "HINODE", "SEIWA", "KOWA", "MARUYAMA", "ISHIDA"]
JP_SUFFIX = {
    "Technology": ["ELECTRONICS CO.,LTD.", "PRECISION CO.,LTD.", "SYSTEMS CORPORATION"],
    "Healthcare": ["PHARMACEUTICAL CO.,LTD.", "MEDICAL CORPORATION"],
    "Financial Services": ["BANK,LTD.", "SECURITIES CO.,LTD.", "FINANCIAL GROUP,INC."],
    "Consumer Cyclical": ["MOTOR CO.,LTD.", "RETAILING CO.,LTD.", "AUTO PARTS CO.,LTD."],
    "Consumer Defensive": ["FOODS CO.,LTD.", "BREWERY CO.,LTD.", "SHOJI CO.,LTD."],
    "Industrials": ["INDUSTRIES,LTD.", "MACHINERY CO.,LTD.", "CONSTRUCTION CO.,LTD.", "LOGISTICS CO.,LTD."],
    "Energy": ["OIL CO.,LTD.", "ENERGY CORPORATION"],
    "Basic Materials": ["CHEMICAL CO.,LTD.", "STEEL CORPORATION", "PAPER CO.,LTD."],
    "Real Estate": ["ESTATE CO.,LTD.", "FUDOSAN CO.,LTD."],
    "Utilities": ["ELECTRIC POWER CO.,INC.", "GAS CO.,LTD."],
    "Communication Services": ["BROADCASTING CO.,LTD.", "MEDIA HOLDINGS,INC.", "NET CORPORATION"],
}
US_MIDDLE = ["", "", "", "Global ", "American ", "First ", "United ", "National ", "Pacific "]
JP_MIDDLE = ["", "", "SEIKI ", "KOGYO ", "DENKI ", "SANGYO ", "TECHNO ", "GIKEN ", "NIPPON "]
ZH_CHARS = list("华中天海恒金永新东博鼎瑞盛嘉宏光远润益联汇凯达安正元星晨德信福隆泰康和兴昌通宇航")
ZH_SUFFIX = {
    "Technology": ["科技", "电子", "芯片", "光电", "信息", "智能"],
    "Healthcare": ["医药", "生物", "药业", "医疗"],
    "Financial Services": ["银行", "证券", "保险", "金融"],
    "Consumer Cyclical": ["汽车", "家电", "服饰", "旅游"],
    "Consumer Defensive": ["食品", "酒业", "乳业", "农业"],
    "Industrials": ["重工", "机械", "电气", "建设", "物流", "装备"],
    "Energy": ["能源", "石化", "煤业"],
    "Basic Materials": ["化工", "新材", "矿业", "钢铁", "有色"],
    "Real Estate": ["地产", "置业", "发展"],
    "Utilities": ["电力", "水务", "燃气", "环保"],
    "Communication Services": ["传媒", "文化", "通信", "网络"],
    UNCLASSIFIED: ["实业", "集团"],
}


def synth_ticker(m: str, rng, used: set) -> str:
    while True:
        if m == "us":
            t = "".join(rng.choice(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), size=int(rng.choice([3, 4], p=[0.45, 0.55]))))
        elif m == "cn":
            prefix = {"sh": ["600", "601", "603", "605"], "sz": ["000", "001", "002", "003"],
                      "cy": ["300", "301"], "kc": ["688"]}[str(rng.choice(["sh", "sz", "cy", "kc"], p=[0.35, 0.25, 0.25, 0.15]))]
            t = f"{rng.choice(prefix)}{int(rng.integers(0, 1000)):03d}"
        elif m == "jp":
            t = f"{int(rng.integers(130, 599))}A" if rng.random() < 0.04 else str(int(rng.integers(1301, 9998)))
        else:
            t = f"{int(rng.integers(10, 9999)):05d}"
        if t not in used:
            used.add(t)
            return t


def synth_name(m: str, sector: str, rng, used: set) -> str:
    for _ in range(1000):
        if m == "us":
            name = f"{rng.choice(US_STEMS)} {rng.choice(US_MIDDLE)}{rng.choice(US_SUFFIX.get(sector, ['Holdings, Inc.']))}"
        elif m == "jp":
            name = f"{rng.choice(JP_STEMS)} {rng.choice(JP_MIDDLE)}{rng.choice(JP_SUFFIX.get(sector, ['HOLDINGS,INC.']))}"
        else:
            name = "".join(rng.choice(ZH_CHARS, size=2)) + str(rng.choice(ZH_SUFFIX[sector]))
            if m == "hk" and rng.random() < 0.35:
                name += "控股"
            elif m == "cn" and rng.random() < 0.2:
                name += "股份"
        if name not in used:
            used.add(name)
            return name
    raise RuntimeError("name space exhausted")


# ---------------------------------------------------------------------------- market configuration
# n: synthetic universe size (= screen count = sector rows). Smaller than live (us 3,281 / cn 5,101 /
# jp 3,503 / hk 1,754) so the files stay small; still far more than the 3 pages a notebook should fetch.
CFG = {
    # Keys: universe size n and last EOD session; market-cap curve (top_cap * rank ** -alpha); price, valuation,
    # margin and dividend levels; day_mkt (index move on the screen session); turnover level / dispersion and the
    # turnover_vs_10d centre; vol (annualised); shifts = market's own excess over MA10/50/200; the ml/clusters
    # archetypes and their (non-contiguous) live-style ids; realtime / hotlist clocks; ml run metadata; screen
    # data_quality percentages (dq); screening exclusions (excl, share of n); whale-board scales.
    "us": dict(
        label="United States", short="US", currency="USD", fx=1.0, offset=-4, n=1000, eod="2026-10-06",
        generated="2026-10-07T05:00:46.731902+00:00", top_cap=5.4e12, alpha=0.88,
        price_mu=math.log(120), price_sd=1.0, sp_base=0.24, bp_base=0.19, dy_base=0.017, pm_base=0.085,
        day_mkt=0.0048, turn_ratio=0.0105, turn_sd=0.35, tv10_shift=-0.10, vol=0.34, shifts=(0.004, -0.03, 0.0),
        benchmark=("sp500", "S&P 500"),
        archetypes=["quality_defensive", "growth", "pullback", "momentum", "speculative", "deep_value", "distressed",
                    "levered", "high_vol", "megacap"],
        cluster_ids=[0, 3, 2, 9, 10, 4, 8, 6, 7, 11],
        rt=dict(status="CLOSED", as_of=utc(2026, 10, 6, 20, 0, 1), secs=23400, elapsed=23398, source="polygon"),
        hot=dict(as_of=utc(2026, 10, 6, 19, 59, 33), n=20),
        ml=dict(as_of="2026-10-05", age=2, finished="2026-10-06T16:36:58.204117+00:00", run="163640"),
        dq=dict(fund=100.0, stmt=98.71, val=100.0, pit=0.0, eps=82.4, bvps=82.12, ps=83.05),
        excl=dict(adr=0.22, non_equity=0.035, no_price=0.235),
        whale=dict(n_funds=100, max_hold=85, deg_scale=1.0, pop=750, share_frac=0.0004, crowd_total=104,
                   communities=8, modularity=0.1874, quarter="2026-06-30", as_of_date="2026-06-30", held_scale=0.95),
    ),
    "cn": dict(
        label="China", short="CN", currency="CNY", fx=7.1184, offset=8, n=1150, eod="2026-09-30",
        generated="2026-10-07T05:02:11.508364+00:00", top_cap=4.4e11, alpha=0.64,
        price_mu=math.log(26), price_sd=0.95, sp_base=0.30, bp_base=0.36, dy_base=0.0012, pm_base=0.06,
        day_mkt=0.0058, turn_ratio=0.0125, turn_sd=0.4, tv10_shift=-0.22, vol=0.38, shifts=(-0.022, -0.06, -0.08),
        benchmark=("csi300", "CSI 300"),
        archetypes=["quality_defensive", "pullback", "distressed", "speculative", "momentum", "levered", "deep_value"],
        cluster_ids=[1, 0, 7, 6, 3, 4, 5],
        rt=dict(status="CLOSED", as_of=utc(2026, 9, 30, 6, 59, 40), secs=14400, elapsed=14379,
                source="akshare_cn_spot_em"),
        hot=dict(as_of=utc(2026, 9, 30, 6, 59, 40), n=20),
        ml=dict(as_of="2026-09-30", age=7, finished="2026-10-02T17:37:49.660218+00:00", run="173731"),
        dq=dict(fund=100.0, stmt=98.36, val=100.0, pit=100.0, eps=97.82, bvps=97.82, ps=97.66),
        excl=dict(adr=0.0, non_equity=0.0, no_price=0.0045),
        whale=dict(n_funds=100, max_hold=60, deg_scale=3.0, pop=4000, share_frac=0.002, crowd_total=25400,
                   communities=3, modularity=0.2361, quarter="2026-Q2", as_of_date="2026-06-30", held_scale=1.0),
    ),
    "jp": dict(
        label="Japan", short="JP", currency="JPY", fx=149.82, offset=9, n=900, eod="2026-10-06",
        generated="2026-10-07T05:15:20.114725+00:00", top_cap=2.9e11, alpha=0.70,
        price_mu=math.log(3200), price_sd=0.95, sp_base=0.57, bp_base=0.62, dy_base=0.02, pm_base=0.025,
        day_mkt=0.0085, turn_ratio=0.0095, turn_sd=0.4, tv10_shift=-0.22, vol=0.27, shifts=(0.0, -0.02, 0.0),
        benchmark=("nikkei225", "Nikkei 225"),
        archetypes=["quality_defensive", "high_vol", "momentum", "levered", "speculative", "growth", "distressed",
                    "pullback", "deep_value"],
        cluster_ids=[0, 2, 1, 3, 5, 4, 9, 6, 8],
        rt=dict(status="OPEN", as_of=utc(2026, 10, 7, 5, 26, 7), secs=19800, elapsed=15967, source="tradingview_tse"),
        hot=dict(as_of=utc(2026, 10, 7, 5, 26, 12), n=0),
        ml=dict(as_of="2026-10-06", age=1, finished="2026-10-06T16:37:40.335871+00:00", run="163724"),
        dq=dict(fund=84.07, stmt=96.12, val=99.9, pit=51.3, eps=90.21, bvps=90.21, ps=90.21),
        excl=dict(adr=0.0, non_equity=0.006, no_price=0.18),
        whale=dict(n_funds=150, max_hold=6, deg_scale=60.0, pop=2500, share_frac=0.3, crowd_total=19800,
                   communities=172, modularity=0.1712, quarter="2026-10-07", as_of_date="2026-10-07", held_scale=0.35),
    ),
    "hk": dict(
        label="Hong Kong", short="HK", currency="HKD", fx=7.7809, offset=8, n=600, eod="2026-10-06",
        generated="2026-10-07T05:15:18.902456+00:00", top_cap=5.0e11, alpha=0.75,
        price_mu=math.log(22), price_sd=1.3, sp_base=0.33, bp_base=0.58, dy_base=0.03, pm_base=0.045,
        day_mkt=0.0068, turn_ratio=0.0014, turn_sd=1.1, tv10_shift=-0.65, vol=0.30, shifts=(-0.01, -0.06, -0.09),
        benchmark=("hsi", "Hang Seng Index"),
        archetypes=["megacap", "distressed", "momentum", "levered", "speculative", "pullback", "deep_value"],
        cluster_ids=[1, 0, 6, 7, 8, 4, 2],
        rt=dict(status="OPEN", as_of=utc(2026, 10, 7, 5, 26, 23), secs=19800, elapsed=10567,
                source="sina_amount_fmp_price_overlay"),
        hot=dict(as_of=utc(2026, 10, 7, 5, 26, 37), n=0),
        ml=dict(as_of="2026-10-06", age=1, finished="2026-10-06T16:38:13.902270+00:00", run="163801"),
        dq=dict(fund=100.0, stmt=99.71, val=100.0, pit=100.0, eps=81.92, bvps=81.92, ps=81.92),
        excl=dict(adr=0.0, non_equity=0.0, no_price=0.34),
        whale=dict(n_funds=150, max_hold=8, deg_scale=2.0, pop=470, share_frac=0.02, crowd_total=702,
                   communities=281, modularity=0.1133, quarter="2026-10-07", as_of_date="2026-10-07", held_scale=0.5),
    ),
}

# Latent style dimensions and archetype centres.
LATENTS = ("mom", "vol", "qual", "val", "grow", "attn", "size", "lev")
ARCHETYPES = {
    "quality_defensive": (0.2, -1.3, 1.3, 0.2, 0.0, -0.8, 0.5, -0.3),
    "growth": (0.5, 0.3, 0.1, -0.7, 2.0, 0.3, 0.0, 0.7),
    "pullback": (-1.8, 1.0, -0.3, 0.2, -0.2, 0.3, -0.3, 0.0),
    "momentum": (2.0, 0.3, 0.2, -0.4, 0.4, 0.5, 0.2, -0.1),
    "speculative": (0.9, 1.7, -1.2, -0.4, 0.5, 2.2, -1.2, 0.0),
    "deep_value": (-0.2, -0.3, 0.3, 2.2, -0.5, -0.6, 0.0, 0.8),
    "distressed": (-0.6, 0.8, -2.2, -1.6, -0.6, 0.2, -0.6, 0.9),
    "levered": (-0.3, 0.2, -0.2, 0.9, -0.3, -0.3, 0.2, 2.6),
    "megacap": (0.5, -0.6, 1.1, -0.7, 0.5, -0.4, 2.2, -0.3),
    "high_vol": (-1.2, 2.1, -0.8, 0.0, 0.0, 0.6, -0.9, 0.3),
}
ARCH_WEIGHT = {"quality_defensive": 3.2, "pullback": 1.4, "distressed": 1.0, "momentum": 1.0, "growth": 1.0,
               "deep_value": 0.9, "levered": 0.6, "speculative": 0.6, "high_vol": 0.5, "megacap": 0.5}
SECTOR_AFFINITY = {
    "Technology": {"growth": 0.6, "momentum": 0.6, "speculative": 0.4, "deep_value": -0.8},
    "Healthcare": {"speculative": 0.8, "distressed": 0.6, "high_vol": 0.5, "deep_value": -0.6},
    "Financial Services": {"deep_value": 0.9, "quality_defensive": 0.5, "levered": 0.7, "speculative": -0.6},
    "Utilities": {"quality_defensive": 1.0, "levered": 0.8, "speculative": -1.0, "momentum": -0.5},
    "Real Estate": {"levered": 1.2, "deep_value": 0.6, "pullback": 0.3},
    "Energy": {"deep_value": 0.8, "pullback": 0.3},
    "Consumer Defensive": {"quality_defensive": 0.9, "deep_value": 0.3},
    "Basic Materials": {"momentum": 0.3, "deep_value": 0.4, "pullback": 0.3},
    "Industrials": {"quality_defensive": 0.3, "momentum": 0.3},
    "Communication Services": {"growth": 0.3, "megacap": 0.3, "speculative": 0.2},
    "Consumer Cyclical": {"growth": 0.2, "pullback": 0.3},
}
ANCHOR_AFFINITY = {"megacap": 2.5, "quality_defensive": 0.8, "momentum": 0.5, "speculative": -2.5, "distressed": -1.5,
                   "high_vol": -1.5}


def round_price(m: str, x):
    x = np.asarray(x, float)
    if m == "jp":
        return np.maximum(np.round(x * 2) / 2, 1.0)  # live JP prices move in 0.5 / 1 yen steps
    if m == "hk":
        return np.where(x < 10, np.round(x, 3), np.round(x, 2))
    return np.maximum(np.round(x, 2), 0.5)


# ---------------------------------------------------------------------------- world model
def build_universe(m: str) -> list[dict]:
    cfg = CFG[m]
    rng = rng_for("universe", m)
    used_t, used_n = set(), set()
    items = []
    for j, (ticker, name, sector, industry) in enumerate(ANCHORS[m]):
        items.append(dict(ticker=ticker, name=name, sector=sector, industry=industry, anchor=j))
        used_t.add(ticker)
        used_n.add(name)
    weights = np.array(SECTOR_WEIGHTS[m], float)
    weights /= weights.sum()
    while len(items) < cfg["n"]:
        if rng.random() < UNCLASSIFIED_SHARE[m]:
            sector, industry = UNCLASSIFIED, None
        else:
            sector = SECTORS[int(rng.choice(len(SECTORS), p=weights))]
            industry = INDUSTRIES[sector][int(min(rng.geometric(0.28) - 1, len(INDUSTRIES[sector]) - 1))]
            if rng.random() < INDUSTRY_NULL_SHARE[m]:
                industry = None
            elif sector in RARE_INDUSTRIES and rng.random() < 0.012:
                industry = str(rng.choice(RARE_INDUSTRIES[sector]))
        items.append(dict(ticker=synth_ticker(m, rng, used_t),
                          name=synth_name(m, sector, rng, used_n), sector=sector, industry=industry, anchor=None))
    return items


def build_world(m: str) -> dict:
    cfg = CFG[m]
    fx = cfg["fx"]
    items = build_universe(m)
    N = len(items)
    rng = rng_for("world", m)
    arch = cfg["archetypes"]
    centers = np.array([ARCHETYPES[a] for a in arch])

    # archetype draw -> latents
    groups = np.zeros(N, int)
    for i, it in enumerate(items):
        logits = np.array([math.log(ARCH_WEIGHT[a]) + SECTOR_AFFINITY.get(it["sector"], {}).get(a, 0.0)
                           + (ANCHOR_AFFINITY.get(a, 0.0) if it["anchor"] is not None else 0.0) for a in arch])
        p = np.exp(logits - logits.max())
        groups[i] = int(rng.choice(len(arch), p=p / p.sum()))
    lat = centers[groups] + 0.55 * rng.standard_normal((N, len(LATENTS)))
    mom, volz, qual, val, grow, attn, size_lat, lev = lat.T

    def z():
        return rng.standard_normal(N)

    def u():
        return rng.random(N)

    sectors = [it["sector"] for it in items]
    industries = [it["industry"] for it in items]
    tickers = [it["ticker"] for it in items]
    is_fin = np.array([s == "Financial Services" for s in sectors])

    # size: rank by latent size (+ noise); anchors take the top ranks in their listed order
    score = size_lat + 0.8 * z()
    for i, it in enumerate(items):
        if it["anchor"] is not None:
            score[i] = 100.0 - 0.01 * it["anchor"] + 0.012 * rng.standard_normal()  # listed order, a few swaps
    order = np.argsort(-score, kind="stable")
    rank = np.empty(N, int)
    rank[order] = np.arange(1, N + 1)
    caps_sorted = np.sort(cfg["top_cap"] * np.arange(1, N + 1) ** (-cfg["alpha"]) * np.exp(0.06 * z()))[::-1]
    cap_usd = np.empty(N)
    cap_usd[order] = caps_sorted
    log_cap = np.log(cap_usd)
    size_z = zs(log_cap)
    cap_local = cap_usd * fx
    price = round_price(m, np.exp(cfg["price_mu"] + cfg["price_sd"] * z() + 0.3 * size_z))
    shares = cap_local / price
    small = rank_pct(-log_cap)  # 0 = largest, 1 = smallest: missing data is more common in small caps
    # rare gaps that live shows even on the three largest-cap screen pages
    big_synth = [int(i) for i in order[:SCREEN_PAGES * PAGE_SIZE] if items[i]["anchor"] is None]
    rare = [int(i) for i in rng.choice(big_synth, size=3, replace=False)]
    if m == "hk":
        for i in rare[:2]:
            items[i]["industry"] = industries[i] = None

    # risk and returns (decimals)
    ann_vol = cfg["vol"] * np.exp(0.30 * volz - 0.12 * size_z + 0.10 * z())
    daily = ann_vol / math.sqrt(252)
    beta = np.clip(1.0 + 0.28 * volz + 0.08 * size_z + 0.2 * z(), -0.2, 2.6)
    ret_252d = np.maximum(np.exp(0.07 + 0.30 * mom + 0.45 * ann_vol * z() - 0.5 * ann_vol ** 2) - 1, -0.93)
    ret_126d = np.exp(0.035 + 0.17 * mom + 0.32 * ann_vol * z()) - 1
    ret_63d = np.exp(0.018 + 0.10 * mom + 0.23 * ann_vol * z()) - 1
    ret_20d = np.exp(0.006 + 0.045 * mom + 0.14 * ann_vol * z()) - 1
    ret_5d = np.exp(0.0015 + 0.012 * mom + 0.10 * ann_vol * z()) - 1
    ytd_return = (1 + ret_252d) ** 0.8 * np.exp(0.08 * z()) - 1
    s10, s50, s200 = cfg["shifts"]  # where the market itself sits versus its moving averages on the fixture day
    pre10 = s10 + 0.55 * ret_5d + 0.125 * ret_20d + 0.01 * (ann_vol / 0.35) * z()  # excess before today's move
    pre50 = s50 + 0.55 * ret_63d + 0.02 * (ann_vol / 0.35) * z()
    pre200 = s200 + 0.5 * ret_252d / (1 + 0.25 * np.abs(ret_252d)) + 0.05 * z()
    cushion = 0.6 * ret_20d + 0.02 * z()
    avwap = price / (1 + cushion)
    rsi = np.clip(50 + 220 * ret_5d / (1 + 4 * ann_vol) + 8 * z(), 4, 96)
    rsi_state = np.where(rsi >= 70, "overbought", np.where(rsi <= 30, "oversold", "neutral"))

    # turnover (local currency): 10-day base, yesterday, today (= the screen session)
    turn_ratio = cfg["turn_ratio"] * np.exp(0.45 * attn + 0.20 * volz - 0.25 * size_z + cfg["turn_sd"] * z())
    T_base = turn_ratio * cap_local
    surge = np.where(u() < 0.06, 0.5 + 0.3 * np.abs(z()), 0.0)
    tv10 = np.exp(cfg["tv10_shift"] + 0.2 * attn + 0.08 * volz + (0.6 if m == "hk" else 0.22) * z() + surge)
    turnover = T_base * tv10
    prev_turnover = T_base * np.exp(0.22 * z())
    to_yest_mult = turnover / prev_turnover

    # one-day change: market x beta + sector shock + weak style links + fat-tailed noise (low R^2 by design)
    sec_shock = {s: 0.006 * float(rng.standard_normal()) for s in SECTORS + [UNCLASSIFIED]}
    idio = daily * rng.standard_t(4, N) / math.sqrt(2)
    change = (cfg["day_mkt"] * beta + np.array([sec_shock[s] for s in sectors]) + 0.003 * np.tanh(mom)
              + 0.008 * np.log(tv10) + idio)
    if m == "cn":  # daily price limits: 20% on ChiNext/STAR, 10% on the main boards
        limit = np.array([0.2 if t[:3] in ("300", "301", "688") else 0.1 for t in tickers])
        change = np.clip(change, -limit, limit)
    else:
        change = np.clip(change, -0.45, 0.8)

    # price / MA - 1 moves almost one for one with today's change (the MA barely moves): a mechanical link, as live
    ma10_ex = np.clip((1 + pre10) * (1 + 0.9 * change) - 1, -0.6, 1.2)
    ma50_ex = np.clip((1 + pre50) * (1 + 0.98 * change) - 1, -0.85, 2.5)
    ma200_ex = np.clip((1 + pre200) * (1 + change) - 1, -0.9, 3.0)
    trend_run = np.abs(ma10_ex) + np.abs(ma50_ex) + np.abs(ma200_ex)

    # fundamentals
    pm = np.clip(cfg["pm_base"] + 0.09 * qual + 0.055 * z() + 0.08 * is_fin, -0.95, 0.8)
    sp = np.exp(math.log(cfg["sp_base"]) + 0.45 * val - 0.25 * grow + 0.6 * z())
    ep = sp * pm * np.exp(0.1 * z())
    bp = np.exp(math.log(cfg["bp_base"]) + 0.55 * val + 0.55 * z()) * np.where(is_fin, 1.8, 1.0)
    if m == "hk":  # live HK revenue growth runs high and wide
        rg = np.exp(math.log(0.85) + 0.35 * grow + 0.9 * z()) - 0.25
    else:
        rg = 0.07 + 0.12 * grow + 0.055 * z() + np.where(u() < 0.03, 1.5 * np.abs(z()), 0.0)
    rg = np.clip(rg, -0.65, 5.0)
    cfop = ep * (0.6 + 0.8 * u()) + 0.01 * z()
    pays = (0.8 * val + 0.5 * qual - 0.6 * grow + 0.6 * z() + {"us": 0.0, "cn": 0.6, "jp": 1.0, "hk": 0.2}[m]) > -0.2
    if m == "cn":
        dy = np.where(pays, np.exp(math.log(cfg["dy_base"]) + 0.5 * val + 1.7 * z()), 0.0)
    else:
        dy = np.where(pays, np.exp(math.log(cfg["dy_base"]) + 0.35 * val + 0.3 * z()), 0.0)
    dy = np.minimum(dy, 0.15)
    pm_null = u() < 0.01 + {"us": 0.25, "cn": 0.03, "jp": 0.05, "hk": 0.30}[m] * small ** 2
    rg_null = u() < 0.01 + {"us": 0.22, "cn": 0.01, "jp": 0.07, "hk": 0.40}[m] * small ** 2
    dy_null = u() < {"us": 0.07, "cn": 0.01, "jp": 0.03, "hk": 1.0}[m]
    ma200_null = u() < (0.02 if m == "us" else 0.0)
    sp_null = u() < (0.007 if m == "jp" else 0.0)
    if m == "jp":
        sp_null[rare[0]] = True
    chg_null = u() < (0.004 if m == "hk" else 0.0)
    chg_null[int(np.argmax(small))] = True  # at least one per market (live: every market has a few)
    ma50_null = u() < (0.003 if m == "us" else 0.0)
    if m == "us":
        ma50_null[rare[0]] = True
    prev_null = u() < (0.003 if m == "hk" else 0.0)
    ratio_quality = np.where(u() < {"us": 0.985, "cn": 0.995, "jp": 0.99, "hk": 0.93}[m], "good", "acceptable")
    revenue_model = np.where(is_fin, "financial", np.where(u() < 0.05, "holding", "industrial"))
    composite_quality = np.where(pm_null | rg_null, np.nan, rg * pm)

    # cap-weighted sector / industry means of the daily change
    chg_out = np.where(chg_null, np.nan, change)
    sector_mean_1d = group_wmean(sectors, chg_out, cap_local)
    industry_mean_1d = group_wmean(industries, chg_out, cap_local, min_members=2)

    # institutional (whale) holdings: count of reporting funds that hold the name
    wcfg = cfg["whale"]
    p_held = np.clip(wcfg["held_scale"] * (0.05 + 0.9 * (1 - small) ** 3), 0, 0.98)
    held = u() < p_held
    n_hold = np.where(held, np.maximum(1, np.round(0.85 * wcfg["max_hold"] * (1 - small) ** 9 * np.exp(0.25 * z()))), 0)
    n_hold = np.minimum(n_hold, wcfg["max_hold"]).astype(int)
    flow = 0.7 * mom + 0.7 * z()
    if m in ("jp", "hk"):  # live JP/HK boards show no "stable" trend
        whale_trend = np.where(flow > -0.9, "accumulating", "distributing")
    else:
        whale_trend = np.where(flow > -0.2, "accumulating", np.where(flow < -1.0, "distributing", "stable"))
    whale_conf = np.where(n_hold >= 0.15 * wcfg["max_hold"] + 1, "high", np.where(n_hold >= 0.05 * wcfg["max_hold"] + 1, "medium", "low"))

    F = dict(price=price, change_pct=chg_out, turnover=turnover, prev_turnover=prev_turnover,
             prev_turnover_out=np.where(prev_null, np.nan, prev_turnover), T_base=T_base,
             tv10=tv10, to_yest_mult=to_yest_mult, market_cap=cap_local, market_cap_usd=cap_usd,
             ma10_excess=ma10_ex, ma50_excess=np.where(ma50_null, np.nan, ma50_ex), ma200_excess=np.where(ma200_null, np.nan, ma200_ex),
             ep=ep, bp=bp, sp=np.where(sp_null, np.nan, sp), profit_margin=np.where(pm_null, np.nan, pm),
             revenue_growth=np.where(rg_null, np.nan, rg), dividend_yield=np.where(dy_null, np.nan, dy),
             cfop=cfop, composite_quality=composite_quality, ret_5d=ret_5d, ret_20d=ret_20d, ret_63d=ret_63d,
             ret_126d=ret_126d, ret_252d=ret_252d, ytd_return=ytd_return, ann_vol=ann_vol, daily=daily, beta=beta,
             avwap=avwap, avwap_cushion=cushion, trend_run=trend_run, rsi_14=rsi, sector_mean_1d=sector_mean_1d,
             industry_mean_1d=industry_mean_1d, turnover_ratio=turnover / cap_local)
    S = dict(ratio_quality=ratio_quality, revenue_model=revenue_model, rsi_state=rsi_state,
             whale_trend=whale_trend, whale_confidence=whale_conf)
    W = dict(m=m, cfg=cfg, items=items, N=N, groups=groups, lat=lat, F=F, S=S, size_z=size_z, log_cap=log_cap,
             rank=rank, by_cap=order, tickers=tickers, sectors=sectors, industries=industries,
             names=[it["name"] for it in items], index={t: i for i, t in enumerate(tickers)}, shares=shares,
             n_hold=n_hold, flow=flow, small=small, surge=surge > 0)
    W["RT"] = realtime_state(W, rng)
    return W


def realtime_state(W: dict, rng) -> dict:
    """Turnover board state. CLOSED markets (us, cn) show the screen session; OPEN markets (jp, hk) show
    today's partial session, whose previous day is the screen session."""
    m, cfg, F, N = W["m"], W["cfg"], W["F"], W["N"]
    rt = cfg["rt"]
    z = lambda: rng.standard_normal(N)  # noqa: E731
    u = lambda: rng.random(N)  # noqa: E731
    secs, elapsed = rt["secs"], rt["elapsed"]
    if rt["status"] == "CLOSED":
        acc = F["turnover"] * (0.80 + 0.18 * u())
        tps = acc / elapsed
        proj = tps * secs
        prev = F["prev_turnover"] * (0.985 + 0.015 * u())
        gap = F["daily"] * 0.7 * z()
        chg = np.nan_to_num(F["change_pct"])
        ret = 100 * ((1 + chg) / (1 + gap) - 1)  # measured from a different reference than change_pct
        price = round_price(m, F["price"] * (1 + 0.0004 * z()))
    else:
        frac = elapsed / secs
        surge1 = np.where(u() < 0.06, 0.5 + 0.3 * np.abs(z()), 0.0)
        full1 = F["T_base"] * np.exp(cfg["tv10_shift"] + 0.25 * z() + surge1)  # today's full-session turnover
        acc = full1 * frac * (1 + 0.15 * (1 - frac))  # sessions are front-loaded a little
        tps = acc / elapsed
        proj = tps * secs
        prev = F["turnover"]  # the screen session is "yesterday" for the open board
        ret1 = cfg["day_mkt"] * -0.6 * F["beta"] + 0.01 * np.log(proj / prev) + F["daily"] * math.sqrt(frac) * \
            rng.standard_t(4, N) / math.sqrt(2)
        ret = 100 * ret1
        price = round_price(m, F["price"] * (1 + ret1))
    return dict(acc=acc, tps=tps, proj=proj, prev=prev, ret=ret, price=price)


# ---------------------------------------------------------------------------- screen
DQ_NOTE = ("Share of the screen universe with a displayable current value. The PIT market-cap figure measures "
           "the share-count evidence clock; dividend yield also needs matching dividend and price currencies.")


def screen_data_quality(W: dict) -> dict:
    cfg, F, N = W["cfg"], W["F"], W["N"]
    dq = cfg["dq"]
    return {
        "coverage": "full", "fund_shares_populated_pct": dq["fund"], "statement_line_populated_pct": dq["stmt"],
        "basis_population": int(round(N * {"us": 1.28, "cn": 1.01, "jp": 1.05, "hk": 1.26}[W["m"]])),
        "validated_market_cap_pct": dq["val"], "market_cap_information_pit_pct": dq["pit"],
        "eps_governed_pct": dq["eps"], "bvps_governed_pct": dq["bvps"],
        "dividend_yield_currency_aligned_pct": round(100 * float(np.isfinite(F["dividend_yield"]).mean()), 2),
        "per_share_currency_pct": dq["ps"], "basis_coverage_note": DQ_NOTE, "limitation": None,
    }


def turnover_value(m: str, x):
    if not math.isfinite(float(x)):
        return None
    if m == "us":
        return round(float(x), 6)
    if m == "hk":
        return round(float(x), 2)
    return money(x)


def screen_row(W: dict, i: int) -> dict:
    m, F, S = W["m"], W["F"], W["S"]
    f = {k: v[i] for k, v in F.items()}
    return {
        "ticker": W["tickers"][i], "company_name": W["names"][i], "sector": W["sectors"][i],
        "industry": W["industries"][i], "price": float(f["price"]), "change_pct": num(f["change_pct"], 6),
        "turnover": turnover_value(m, f["turnover"]),
        "previous_day_turnover": None if m == "cn" else turnover_value(m, f["prev_turnover_out"]),
        "turnover_vs_10d": num(f["tv10"]), "market_cap_usd": int(round(float(f["market_cap_usd"]))),
        "ma10_excess": num(f["ma10_excess"]), "ma50_excess": num(f["ma50_excess"]),
        "ma200_excess": num(f["ma200_excess"]), "ep": num(f["ep"]), "bp": num(f["bp"]), "sp": num(f["sp"]),
        "profit_margin": num(f["profit_margin"]), "revenue_growth": num(f["revenue_growth"]),
        "dividend_yield": num(f["dividend_yield"], 6), "ratio_quality": str(S["ratio_quality"][i]),
        "institutional_default": True,
    }


def screen_payloads(W: dict) -> dict[str, dict]:
    """Pages 1..SCREEN_PAGES of the default sort (market_cap_usd, largest first)."""
    m, cfg, N = W["m"], W["cfg"], W["N"]
    pages = math.ceil(N / PAGE_SIZE)
    dq = screen_data_quality(W)
    out = {}
    for page in range(1, SCREEN_PAGES + 1):
        idx = W["by_cap"][(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        out[f"screen_{m}.json" if page == 1 else f"screen_{m}.page{page}.json"] = {
            "ok": True, "schema_version": "surgeflow.market_screen.v1", "market": m, "as_of_date": cfg["eod"],
            "generated_at": cfg["generated"], "page": page, "page_size": PAGE_SIZE, "total_pages": pages,
            "count": N, "data_quality": dq, "rows": [screen_row(W, int(i)) for i in idx],
        }
    return out


# ---------------------------------------------------------------------------- sector
SECTOR_KEY_ORDER = {  # live key order differs by market (backend serialisation); kept for realism
    "us": ("whale_confidence", "whale_fund_count", "is_microcap", "name", "ticker", "sector_mean_1d", "sector",
           "industry_mean_1d", "industry", "market", "change_pct", "whale_trend"),
    "jp": ("industry", "industry_mean_1d", "whale_trend", "whale_fund_count", "market", "sector", "sector_mean_1d",
           "name", "ticker", "whale_confidence", "is_microcap", "change_pct"),
}
SECTOR_KEY_ORDER["cn"], SECTOR_KEY_ORDER["hk"] = SECTOR_KEY_ORDER["us"], SECTOR_KEY_ORDER["jp"]


def sector_payload(W: dict) -> dict:
    m, cfg, F, S, N = W["m"], W["cfg"], W["F"], W["S"], W["N"]
    rng = rng_for("sector", m)
    rows = []
    for i in rng.permutation(N):  # backend order, not sorted
        i = int(i)
        held = W["n_hold"][i] > 0
        rec = {
            "whale_confidence": str(S["whale_confidence"][i]) if held else None,
            "whale_fund_count": int(W["n_hold"][i]) if held else None,
            "is_microcap": bool(F["market_cap_usd"][i] < 7e6), "name": W["names"][i], "ticker": W["tickers"][i],
            "sector_mean_1d": num(F["sector_mean_1d"][i], 6), "sector": W["sectors"][i],
            "industry_mean_1d": num(F["industry_mean_1d"][i], 6), "industry": W["industries"][i], "market": m,
            "change_pct": num(F["change_pct"][i], 6), "whale_trend": str(S["whale_trend"][i]) if held else None,
        }
        rows.append({k: rec[k] for k in SECTOR_KEY_ORDER[m]})
    ex = cfg["excl"]
    adr, non_eq, no_price = (int(round(N * ex[k])) for k in ("adr", "non_equity", "no_price"))
    pmn = int(np.sum(~np.isfinite(F["profit_margin"])))
    rgn = int(np.sum(~np.isfinite(F["revenue_growth"])))
    ratio_missing = int(np.sum(~np.isfinite(F["sp"]) | ~np.isfinite(F["ep"]) | ~np.isfinite(F["bp"])))
    q = Counter(S["ratio_quality"].tolist())
    rm = Counter(S["revenue_model"].tolist())
    qa = {
        "total_fund": N + adr + non_eq + no_price, "excluded_adr": adr, "excluded_non_equity": non_eq,
        "excluded_no_price": no_price, "excluded_no_fundamentals": 0, "screened_total": N, "all_4_missing": 0,
        "any_missing": ratio_missing, "missing_source_null": ratio_missing, "missing_sanity_capped": 0,
        "ep_gt_sp": int(np.sum(np.nan_to_num(F["ep"], nan=-9) > np.nan_to_num(F["sp"], nan=9))),
        "bp_gt_100pct": int(np.sum(F["bp"] > 1)), "quality_good": q["good"], "quality_acceptable": q["acceptable"],
        "quality_suspect": 0, "quality_unusable": 0, "revenue_model_industrial": rm["industrial"],
        "revenue_model_financial": rm["financial"], "revenue_model_holding": rm["holding"], "null_sector": 0,
        "null_industry": sum(1 for x in W["industries"] if x is None), "null_profit_margin": pmn,
        "null_revenue_growth": rgn,
    }
    data = {
        "ok": True, "method": "page_sector_v1", "market": m, "tab": "sector", "as_of_date": cfg["eod"],
        "generated_at": cfg["generated"], "filter_version": "2.0.0", "ratio_schema_version": "1.1.0",
        "qa_summary": qa, "market_fundamentals_status": screen_data_quality(W), "count": N, "rows": rows,
    }
    return {"ok": True, "schema_version": "surgeflow.market_sector.v1", "source": "/api/page/sector", "market": m,
            "data": data}


# ---------------------------------------------------------------------------- realtime + hotlist
def board_meta(W: dict, as_of: datetime, schema: str, source, quality: str, stale_reason, rows: list) -> dict:
    cfg = W["cfg"]
    return {"schema_version": schema, "market": W["m"], "as_of_utc": iso(as_of),
            "as_of_local": local_iso(as_of, cfg["offset"]), "market_status": cfg["rt"]["status"], "source": source,
            "cache_ttl_seconds": 60, "data_quality": quality, "stale_reason": stale_reason, "count": len(rows),
            "rows": rows}


def realtime_payload(W: dict, limit: int = 50) -> dict:
    cfg, RT = W["cfg"], W["RT"]
    rows = []
    for rank, i in enumerate(np.argsort(-RT["proj"])[:limit], 1):
        rows.append({
            "rank": rank, "ticker": W["tickers"][i], "company_name": W["names"][i], "price": float(RT["price"][i]),
            "intraday_return_pct": num(RT["ret"][i]), "turnover_per_second": num(RT["tps"][i], 2),
            "accumulated_turnover": money(RT["acc"][i]), "projected_turnover": money(RT["proj"][i]),
            "projected_vs_yesterday": num(RT["proj"][i] / RT["prev"][i], 6),
            "previous_day_turnover": money(RT["prev"][i]),
        })
    closed = cfg["rt"]["status"] == "CLOSED"
    data = board_meta(W, cfg["rt"]["as_of"], "addin.realtime.v1", cfg["rt"]["source"],
                      "stale" if closed else "ok", "market_closed" if closed else None, rows)
    return {"ok": True, "schema_version": "surgeflow.market_realtime.v1", "source_schema_version": "addin.realtime.v1",
            "data": data}


def factor_style(W: dict, i: int) -> str:
    F = W["F"]
    lat = W["lat"][i]
    labels = [
        "Market Long",
        "Large Cap" if W["size_z"][i] > 0.5 else "Small Cap",
        "Value" if lat[3] > 0.3 else "Growth",
        "Momentum" if F["ret_252d"][i] > np.nanmedian(F["ret_252d"]) else "Reversal",
        "Strong Quality" if lat[2] > 0 else "Weak Quality",
        "Conservative" if lat[1] < 0 else "Aggressive",
        "Liquid" if F["turnover_ratio"][i] > np.nanmedian(F["turnover_ratio"]) else "Illiquid",
    ]
    return " / ".join(labels)


def hotlist_members(W: dict) -> list[int]:
    RT, F = W["RT"], W["F"]
    target = W["cfg"]["hot"]["n"]
    if not target:
        return []
    pvy = RT["proj"] / RT["prev"]
    for threshold in (2.0, 1.6, 1.3, 1.1):
        ok = np.where((pvy > threshold) & (RT["ret"] > 0) & (F["market_cap_usd"] > 5e8))[0]
        if len(ok) >= target:
            break
    return [int(i) for i in sorted(ok, key=lambda i: -RT["proj"][i])[:target]]


def hotlist_payload(W: dict) -> dict:
    cfg, RT, F = W["cfg"], W["RT"], W["F"]
    fx = cfg["fx"]
    rows = []
    for rank, i in enumerate(hotlist_members(W), 1):
        rows.append({
            "hotlist_rank": rank, "market": cfg["short"], "ticker": W["tickers"][i], "company_name": W["names"][i],
            "industry": W["industries"][i], "factor_style": factor_style(W, i), "price": float(RT["price"][i]),
            "intraday_return_pct": num(RT["ret"][i]), "turnover_per_second": money(RT["tps"][i] / fx),
            "market_cap_usd": money(F["market_cap_usd"][i]), "projected_turnover_usd": money(RT["proj"][i] / fx),
            "projected_vs_yesterday": num(RT["proj"][i] / RT["prev"][i], 6),
            "previous_day_turnover_usd": money(RT["prev"][i] / fx),
        })
    if rows:
        quality, reason = ("stale", "market_closed") if cfg["rt"]["status"] == "CLOSED" else ("ok", None)
    else:  # live jp/hk on 2026-10-07: an empty board during an open session
        quality, reason = "empty", "no_current_hotlist_members"
    data = board_meta(W, cfg["hot"]["as_of"], "addin.hotlist.v1", None, quality, reason, rows)
    return {"ok": True, "schema_version": "surgeflow.market_hotlist.v1", "source_schema_version": "addin.hotlist.v1",
            "data": data}


# ---------------------------------------------------------------------------- ml clusters
# ML features (live vocabulary) as loadings on the latents (mom, vol, qual, val, grow, attn, size, lev).
ML_FEATURES = {
    "ret_20d": (0.6, 0, 0, 0, 0, 0.3, 0, 0), "ret_63d": (0.9, 0, 0, 0, 0, 0, 0, 0),
    "ret_126d": (1.0, 0, 0, 0, 0, 0, 0, 0), "ret_252d": (0.9, 0, 0, 0, 0.2, 0, 0, 0),
    "rv_20": (0, 0.8, 0, 0, 0, 0.4, 0, 0), "rv_63": (0, 0.9, 0, 0, 0, 0.2, 0, 0), "rv_252": (0, 1.0, 0, 0, 0, 0, 0, 0),
    "downside_vol_63": (-0.3, 0.8, 0, 0, 0, 0, 0, 0), "vol_of_vol_63": (0, 0.7, 0, 0, 0, 0.3, 0, 0),
    "residual_vol_252_d": (0, 0.9, 0, 0, 0, 0, -0.3, 0), "beta_252_d": (0.2, 0.5, 0, 0, 0, 0, 0, 0),
    "max_drawdown_252": (0.5, -0.8, 0, 0, 0, 0, 0, 0), "distance_from_high_252": (0.7, -0.4, 0, 0, 0, 0, 0, 0),
    "rolling_sharpe_63": (0.8, -0.3, 0, 0, 0, 0, 0, 0), "r2_252_d": (0.6, 0, 0, 0, 0, 0, 0.3, 0),
    "profit_margin": (0, 0, 1.0, 0, 0, 0, 0, 0), "revenue_growth": (0, 0, 0, 0, 1.0, 0, 0, 0),
    "ni_growth": (0, 0, 0.4, 0, 0.6, 0, 0, 0), "cfo_growth": (0, 0, 0.3, 0, 0.5, 0, 0, 0),
    "leverage_debt_to_mcap": (0, 0, 0, 0, 0, 0, 0, 1.0), "val_ep_z": (0, 0, 0.5, 0.8, 0, 0, 0, 0),
    "val_bp_z": (0, 0, 0, 0.9, 0, 0, 0, 0), "val_cfop_z": (0, 0, 0.4, 0.7, 0, 0, 0, 0),
    "log_market_cap": (0, 0, 0, 0, 0, 0, 1.0, 0), "turnover_to_mcap": (0, 0.2, 0, 0, 0, 0.9, 0, 0),
    "pa_mfe_21d": (0.6, 0.3, 0, 0, 0, 0.5, 0, 0), "pa_mae_21d": (0.5, -0.6, 0, 0, 0, 0, 0, 0),
    "pa_edge_21d": (0.8, 0, 0, 0, 0, 0.2, 0, 0), "pa_mfe_52w": (0.7, 0.4, 0, 0, 0, 0, 0, 0),
    "pa_mae_52w": (0.4, -0.7, 0, 0, 0, 0, 0, 0), "pa_edge_52w": (0.8, 0, 0, 0, 0, 0, 0, 0),
    "pa_sir_infectious": (0, 0, 0, 0, 0, 0.8, 0, 0), "pa_sir_recovered": (0, 0.2, 0, 0, 0, 0.9, 0, 0),
}
ML_NAMES = list(ML_FEATURES)
# (feature, sign) -> the cluster-name phrase used live; features without a phrase are skipped when naming
PHRASES = {
    ("profit_margin", 1): "high margin", ("profit_margin", -1): "low margin",
    ("rv_63", -1): "low volatility (3m)", ("rv_63", 1): "high volatility (3m)",
    ("rv_252", -1): "low volatility (1y)", ("rv_252", 1): "high volatility (1y)",
    ("max_drawdown_252", 1): "shallow drawdown", ("max_drawdown_252", -1): "deep drawdown",
    ("residual_vol_252_d", -1): "low idio vol", ("revenue_growth", 1): "high growth",
    ("ni_growth", 1): "rising earnings", ("ni_growth", -1): "falling earnings",
    ("leverage_debt_to_mcap", 1): "high leverage", ("pa_mae_21d", -1): "deep pullbacks (21d)",
    ("downside_vol_63", 1): "high downside vol", ("pa_mfe_21d", 1): "wide upside excursions (21d)",
    ("pa_edge_21d", 1): "favorable excursion edge", ("ret_252d", 1): "strong 1y momentum",
    ("pa_sir_recovered", 1): "attention spent", ("pa_sir_infectious", -1): "attention quiet",
    ("val_ep_z", -1): "expensive (low E/P)", ("val_ep_z", 1): "cheap (high E/P)",
    ("val_cfop_z", -1): "low cash yield", ("val_cfop_z", 1): "high cash yield",
    ("val_bp_z", 1): "cheap (high B/P)", ("val_bp_z", -1): "rich (low B/P)",
    ("turnover_to_mcap", 1): "high turnover", ("pa_mfe_52w", 1): "wide 1y upside range",
    ("beta_252_d", 1): "high beta", ("pa_edge_52w", 1): "favorable 1y edge", ("pa_mae_52w", -1): "deep 1y drawdowns",
    ("log_market_cap", 1): "large cap", ("ret_63d", 1): "rising (3m)", ("ret_63d", -1): "falling (3m)",
    ("rolling_sharpe_63", -1): "poor risk-adj return",
}
ML_GUARDRAILS = [
    "Macro inputs enter only as per-ticker sensitivities, never as same-day macro levels.",
    "Each valuation ratio is used once, so the same signal is not counted twice.",
    "Fundamentals and ownership are carried forward with an explicit age; stale inputs lower coverage.",
    "Every run records coverage and freshness; an old run is labelled stale instead of being hidden.",
]


def kmeans(X: np.ndarray, k: int, rng, iters: int = 40) -> np.ndarray:
    """Plain Lloyd k-means with k-means++ seeding (deterministic given rng)."""
    n = len(X)
    cent = [X[int(rng.integers(n))]]
    for _ in range(1, k):
        d2 = np.min(((X[:, None, :] - np.array(cent)[None]) ** 2).sum(-1), axis=1)
        cent.append(X[int(rng.choice(n, p=d2 / d2.sum()))])
    C = np.array(cent)
    labels = np.zeros(n, int)
    for _ in range(iters):
        labels = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
        C = np.array([X[labels == j].mean(0) if np.any(labels == j) else C[j] for j in range(k)])
    return labels


def silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    D = np.sqrt(np.maximum(((X[:, None, :] - X[None]) ** 2).sum(-1), 0))
    ks = np.unique(labels)
    s = np.zeros(len(X))
    for i in range(len(X)):
        own = labels == labels[i]
        a = D[i, own].sum() / max(own.sum() - 1, 1)
        b = min(D[i, labels == j].mean() for j in ks if j != labels[i])
        s[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(s.mean())


def cluster_name(top: list[tuple[str, float]], used: set) -> str:
    phrases = []
    for feat, v in top:
        p = PHRASES.get((feat, 1 if v > 0 else -1))
        if p and p not in phrases:
            phrases.append(p)
    name = " · ".join(phrases[:3])
    if name in used and len(phrases) > 3:
        name = " · ".join(phrases[:2] + phrases[3:4])
    used.add(name)
    return name


def ml_state(W: dict) -> dict:
    """Features, SurgeFlow-style cluster labels, anomalies and switchers for one market."""
    m, N = W["m"], W["N"]
    rng = rng_for("ml", m)
    L = np.array([ML_FEATURES[f] for f in ML_NAMES])  # (features, latents)
    lat = W["lat"].copy()
    lat[:, 6] = W["size_z"] * 1.2  # the size latent is read from the actual market cap
    X = lat @ L.T + 0.5 * rng.standard_normal((N, len(ML_NAMES)))
    # a few genuine outliers for the anomaly watch
    n_out = max(30, int(0.03 * N))
    outliers = rng.choice(N, size=n_out, replace=False)
    for i in outliers:
        cols = rng.choice(len(ML_NAMES), size=int(rng.integers(3, 6)), replace=False)
        X[i, cols] += rng.choice([-1, 1], size=len(cols)) * rng.uniform(3.5, 6.5, size=len(cols))
    med = np.median(X, axis=0)
    iqr = np.subtract(*np.percentile(X, [75, 25], axis=0))
    Z = np.clip((X - med) / (iqr / 1.349), -8, 8)
    coverage = np.clip(1 - np.abs(rng.normal(0, 0.06, N)) - 0.25 * W["small"] * rng.random(N), 0.5, 1.0)
    eligible = coverage >= 0.6
    # SurgeFlow's partition: nearest archetype centroid in feature space, with some consensus noise
    arch_centroids = np.array([Z[W["groups"] == g].mean(0) for g in range(len(W["cfg"]["archetypes"]))])
    d = np.sqrt(((Z[:, None, :] - arch_centroids[None]) ** 2).sum(-1))
    labels = np.argmin(d + 0.6 * rng.standard_normal(d.shape), axis=1)
    sorted_d = np.sort(d, axis=1)
    confidence = np.clip(1 / (1 + np.exp(-(sorted_d[:, 1] - sorted_d[:, 0]) * 1.4)) * 1.25 - 0.25, 0.34, 1.0)
    second = np.argsort(d, axis=1)[:, 1]
    changed = (rng.random(N) < 0.55 * (1 - confidence) + 0.05) & eligible
    prior = np.where(changed, second, labels)
    return dict(Z=Z, labels=labels, eligible=eligible, coverage=coverage, confidence=confidence, prior=prior,
                changed=changed, outliers=set(int(i) for i in outliers))


def ml_payload(W: dict) -> dict:
    m, cfg, N = W["m"], W["cfg"], W["N"]
    rng = rng_for("ml_payload", m)
    st = W["ML"]
    Z, labels, el = st["Z"], st["labels"], st["eligible"]
    idx = np.where(el)[0]
    k = len(cfg["archetypes"])
    sizes = Counter(labels[idx].tolist())
    order = sorted(range(k), key=lambda g: -sizes[g])
    cid = {g: cfg["cluster_ids"][r] for r, g in enumerate(order)}  # ids follow size order, not contiguous
    in_screen = set(W["by_cap"][:SCREEN_PAGES * PAGE_SIZE].tolist())
    cent = {g: Z[idx][labels[idx] == g].mean(0) for g in range(k)}
    dist = np.array([np.sqrt(((Z[i] - cent[labels[i]]) ** 2).sum()) for i in range(N)])
    # PCA reconstruction error (6 components) on the eligible rows
    Ze = Z[idx] - Z[idx].mean(0)
    _, _, Vt = np.linalg.svd(Ze, full_matrices=False)
    P = Vt[:6]
    resid = Ze - (Ze @ P.T) @ P
    recon = np.full(N, np.nan)
    recon[idx] = (resid ** 2).mean(1)
    recon *= 0.07 / np.nanmedian(recon)
    used_names: set = set()
    names, clusters = {}, []
    for g in order:
        members = idx[labels[idx] == g]
        cz = Z[members].mean(0)
        top_idx = np.argsort(-np.abs(cz))
        top = [(ML_NAMES[j], round(float(cz[j]), 2)) for j in top_idx]
        names[g] = cluster_name(top, used_names)
        mix = Counter("Unknown" if W["sectors"][i] == UNCLASSIFIED else W["sectors"][i] for i in members)
        near = sorted(members, key=lambda i: dist[i])
        reps = [i for i in near if i in in_screen][:6]
        reps += [i for i in near if i not in reps][: 8 - len(reps)]
        clusters.append({
            "cluster_id": cid[g], "cluster_name": names[g], "ticker_count": int(len(members)),
            "sector_mix": dict(mix.most_common(6)), "representative_tickers": [W["tickers"][i] for i in reps],
            "top_features": dict(top[:6]), "jaccard_vs_prior": None, "membership_entrants": None,
            "membership_leavers": None,
        })
    # anomaly watch: worst fit to the map (centroid distance and reconstruction error, rank-combined)
    combo = np.full(N, -np.inf)
    combo[idx] = rank_pct(dist[idx]) + rank_pct(recon[idx])
    score = np.zeros(N)
    score[idx] = rank_pct(combo[idx])
    anomaly_total = int(round(0.02 * len(idx)))
    watch = []
    for i in np.argsort(-combo)[:40]:
        zi = np.clip(Z[i], -5, 5)
        drivers = np.argsort(-np.abs(zi))[:4]
        cov = st["coverage"][i]
        watch.append({
            "ticker": W["tickers"][i], "cluster_id": cid[labels[i]], "cluster_name": names[labels[i]],
            "anomaly_score": round(float(score[i]) * 0.995 + 0.004, 4),
            "pca_reconstruction_error": round(float(recon[i]), 5), "centroid_distance": round(float(dist[i]), 4),
            "coverage_ratio": None if m == "cn" else round(float(cov), 3),  # live CN reports no coverage here
            "low_coverage": bool(cov < 0.8),
            "top_drivers": [{"feature": ML_NAMES[j], "z": round(float(zi[j]), 2)} for j in drivers],
        })
    # switchers since the previous run
    ch = [i for i in idx if st["changed"][i]]
    ch = sorted(ch, key=lambda i: (-st["confidence"][i], W["tickers"][i]))
    ch = [i for i in ch if i in in_screen][:20] + [i for i in ch if i not in in_screen][:20]
    retired = max(cfg["cluster_ids"]) + 1 if m == "hk" else None  # live HK: a prior cluster id that no longer exists
    changed_group = []
    for n_, i in enumerate(sorted(ch, key=lambda i: -st["confidence"][i])):
        from_g = int(st["prior"][i])
        gone = retired is not None and n_ % 2 == 0
        changed_group.append({
            "ticker": W["tickers"][i], "from_cluster_id": retired if gone else cid[from_g],
            "from_cluster_name": None if gone else names[from_g], "to_cluster_id": cid[labels[i]],
            "to_cluster_name": names[labels[i]], "cluster_confidence": round(float(st["confidence"][i]), 3),
            "days_in_cluster": 1,
        })
    # quality block
    Ze_raw = Z[idx]
    sub = rng.choice(len(idx), size=min(700, len(idx)), replace=False)
    sil = silhouette(Ze_raw[sub], labels[idx][sub])
    k_scan = []
    for kk in range(6, 11):
        lab = kmeans(Ze_raw, kk, rng_for("kscan", m, kk))
        k_scan.append({"k": kk, "silhouette": round(silhouette(Ze_raw[sub], lab[sub]), 4),
                       "max_share": round(max(Counter(lab.tolist()).values()) / len(idx), 4)})
    shares = np.array([sizes[g] for g in order]) / len(idx)
    entropy = float(-(shares * np.log(shares)).sum())
    universe = int(round(N * 1.06))
    as_of = cfg["ml"]["as_of"]
    run = {
        "run_id": f"ml_{m}_{as_of}_{cfg['ml']['run']}", "market": m, "as_of_date": as_of, "age_days": cfg["ml"]["age"],
        "stale": cfg["ml"]["age"] > 3, "run_finished_at": cfg["ml"]["finished"], "universe_ticker_count": universe,
        "eligible_count": int(len(idx)), "clustered_ticker_count": int(len(idx)),
        "avg_coverage_ratio": round(float(st["coverage"][idx].mean()), 3), "has_prior_comparison": True,
        "quality": {
            "k": k, "silhouette": round(sil, 4), "realized_max_cluster_share": round(float(shares.max()), 4),
            "balance_cap": 0.4, "balance_cap_satisfied": bool(shares.max() <= 0.4),
            "size_entropy": round(entropy, 4), "effective_clusters": round(math.exp(entropy), 2), "n_clusters": k,
            "k_scan": k_scan, "cluster_sizes": [int(sizes[g]) for g in order],
            "anomaly_intensity": {
                "recon_median": round(float(np.nanmedian(recon)), 6),
                "recon_p95": round(float(np.nanpercentile(recon, 95)), 6),
                "recon_p99": round(float(np.nanpercentile(recon, 99)), 6),
                "centroid_median": round(float(np.median(dist[idx])), 5),
                "centroid_p95": round(float(np.percentile(dist[idx], 95)), 5),
                "pct_vs_trailing": round(float(rng.uniform(0.05, 0.95)), 4), "trailing_runs": int(rng.integers(20, 26)),
                "legs_correlation": round(float(np.corrcoef(dist[idx], recon[idx])[0, 1]), 4),
                "note": "recon_p95 is the run's 95th-percentile PCA reconstruction error; pct_vs_trailing ranks it "
                        "against the trailing runs. Synthetic fixture values.",
            },
            "interpretation": "Silhouette measures how well separated the consensus partition is (-1..1, higher is "
                              "better). Values near 0.1-0.2 are typical for overlapping equity styles.",
        },
        "partition_stability": None,
    }
    notes = {
        "cluster_count": k, "clustered_ticker_count": int(len(idx)), "anomaly_count_p95": anomaly_total,
        "avg_confidence": round(float(st["confidence"][idx].mean()), 3),
        "changed_count": int(np.sum(st["changed"][idx])), "feature_count": None if m == "cn" else len(ML_NAMES),
        "feature_set_version": "multi_market_v2_1", "model_version": "unsupervised_features_only_step1",
        "cluster_model_version": "kmeans_gmm_hier_consensus_v1", "estimator_count": 3,
        "methodology": "Per-ticker features are robust-scaled (median/IQR) and winsorised, then clustered by a "
                       "consensus of k-means, a Gaussian mixture and hierarchical clustering. Anomalies combine "
                       "PCA reconstruction error with distance to the cluster centroid.",
        "guardrails": list(ML_GUARDRAILS),
        "disclaimer": "An unsupervised description of how the market groups today. Not a prediction and not "
                      "investment advice.",
    }
    W["ml_names"], W["ml_cid"] = names, cid
    data = {"available": True, "market": m, "run": run, "clusters": clusters, "anomaly_watch": watch,
            "anomaly_total": anomaly_total, "changed_group": changed_group, "model_notes": notes}
    return {"ok": True, "schema_version": "surgeflow.ml_clusters.v1", "source": "/api/ml/latest", "market": m,
            "data": data}


# ---------------------------------------------------------------------------- whales
SIGNAL_IDS = ["whale_activist_tracker", "whale_cohort_clusters", "whale_consensus_score", "whale_conviction_index",
              "whale_crowdedness", "whale_early_mover", "whale_lead_lag", "whale_letter_nlp", "whale_ll_predictive",
              "whale_network", "whale_position_delta", "whale_sector_tilts", "whale_spillover_hawkes",
              "whale_style_attribution"]
GATE_SIGNALS = {  # which signal families are gated per market (live), and how many gate rows the fixture keeps
    "us": (SIGNAL_IDS, 60), "cn": ([s for s in SIGNAL_IDS if s not in ("whale_activist_tracker", "whale_lead_lag",
                                                                       "whale_letter_nlp")], 90),
    "jp": (["whale_consensus_score", "whale_conviction_index", "whale_crowdedness", "whale_position_delta",
            "whale_network", "whale_ll_predictive", "whale_cohort_clusters", "whale_sector_tilts",
            "whale_style_attribution", "whale_spillover_hawkes"], 100),
    "hk": (["whale_consensus_score", "whale_conviction_index", "whale_crowdedness", "whale_position_delta",
            "whale_network", "whale_ll_predictive"], 100),
}
FUND_WORDS = (["Harbor Point", "Northbridge", "Calder Ridge", "Whitestone", "Bluefin", "Sagebrook", "Meridian Peak",
               "Ashford Lane", "Copperleaf", "Lantern Rock", "Eastwind", "Silver Fir", "Granite Hollow", "Tallgrass",
               "Oakhaven", "Redcliff", "Stillwater Bay", "Kingsmere", "Ironbridge", "Larchmont", "Pelican Shore",
               "Quarry Hill", "Rosewood Lane", "Seabright", "Thornfield", "Upland Ridge", "Valleyview", "Westerly",
               "Yellowpine", "Zephyr Hill", "Amberfield", "Birchwood", "Cascade Point", "Dovetail", "Elmstead"],
              ["Capital Management LLC", "Partners LP", "Advisors", "Asset Management", "Global Investors",
               "Investment Group", "Equity Partners", "Capital Advisors"])


def fund_roster(m: str, n: int, rng) -> list[tuple[str, str]]:
    """(fund_name, fund_id) pairs; the id formats follow the live markets."""
    out, used = [], set()
    while len(out) < n:
        if m == "us":
            name = f"{rng.choice(FUND_WORDS[0])} {rng.choice(FUND_WORDS[1])}"
        elif m == "cn":
            name = "".join(rng.choice(ZH_CHARS, size=2)) + str(rng.choice(
                ["成长混合", "价值精选", "新兴产业", "稳健回报", "科技先锋", "均衡配置"])) + str(rng.choice(["-A", "-C", ""]))
        elif m == "jp":
            name = f"{rng.choice(JP_STEMS)} {rng.choice(['ASSET MANAGEMENT CO.,LTD.', 'TRUST BANK,LTD.', 'LIFE INSURANCE COMPANY', 'CAPITAL PARTNERS'])}"
        else:
            name = (f"{rng.choice(['Harbour', 'Peak', 'Victoria', 'Kowloon', 'Jade', 'Lantau', 'Pearl', 'Lion Rock'])} "
                    f"{rng.choice(['Crest', 'Gate', 'Bay', 'Tower', 'Ridge', 'Point', 'Garden', 'Summit'])} "
                    f"{rng.choice(['Capital Limited', 'Asset Management Limited', 'Investment Partners'])}")
        if name in used:
            continue
        used.add(name)
        fid = {"us": f"FMP:{int(rng.integers(1_000_000, 2_000_000)):010d}", "cn": f"{int(rng.integers(1, 30000)):06d}",
               "jp": f"jpmaj:{name}", "hk": name}[m]
        out.append((name, fid))
    return out


def whales_state(W: dict) -> dict:
    """Six signal boards (top 20 each) plus fund metadata; shared by the whales and notes payloads."""
    m, cfg, F, N = W["m"], W["cfg"], W["F"], W["N"]
    wc = cfg["whale"]
    rng = rng_for("whales", m)
    n_total = wc["n_funds"]
    funds = fund_roster(m, n_total, rng)
    n_hold = W["n_hold"]
    held = np.where(n_hold >= 1)[0]
    qual = W["lat"][:, 2]
    avg_pct = np.minimum(np.exp(math.log(1.5) + 1.2 * rng.standard_normal(N) + 0.3 * qual), 100.0)
    aum_pct = np.minimum(avg_pct * np.exp(0.4 * rng.standard_normal(N)), 100.0)
    mv = n_hold * F["market_cap"] * 0.012 * np.exp(0.5 * rng.standard_normal(N))
    if m == "cn":  # live CN: market value is often not disclosed (0.0) and small otherwise
        mv = np.where(rng.random(N) < 0.3, 0.0, mv * 0.0005)
    quarter, as_of_date = wc["quarter"], wc["as_of_date"]
    long_q = "2026年2季度股票投资明细"  # live CN disclosure label used by some boards
    base_time = {"us": utc(2026, 10, 7, 1, 18), "cn": utc(2026, 10, 7, 1, 19), "jp": utc(2026, 10, 7, 1, 18),
                 "hk": utc(2026, 10, 7, 1, 18)}[m]

    def base(i, board, k_):
        q = quarter
        if m == "cn":
            q = long_q if board in ("conviction", "network") or (board != "consensus" and k_ % 2 == 1) \
                or (board == "consensus" and k_ >= 10) else "2026-Q2"
        a = as_of_date
        if m == "jp" and board == "network":
            q = a = "2026-10-06"
        return {"market": m, "ticker": W["tickers"][i], "quarter": q, "as_of_date": a}

    def finish(row, version, i, minutes, null_name=False):
        row["methodology_version"] = version
        row["updated_at"] = stamp(rng, base_time + timedelta(minutes=minutes), 0.5)
        row["stock_name"] = None if null_name else W["names"][i]
        return row

    boards = {}
    zh = lambda x: zs(x[held])  # noqa: E731
    pop = max(len(held), wc["pop"])

    def pctl(r_):  # percentile of the r_-th leader (0-based) within the board's ranked population
        return round(100.0 * (1 - r_ / pop), 4)
    # consensus
    cs = 0.4 * zh(n_hold) + 0.3 * zh(aum_pct) + 0.1 * zh(avg_pct) + 0.2 * zh(np.log1p(mv))
    rows = []
    for r_, j in enumerate(np.argsort(-cs)[:20]):
        i = held[j]
        comp = {"weights": {"aum_weighted_portfolio_pct": 0.3, "avg_portfolio_pct": 0.1, "log_total_market_value": 0.2,
                            "n_funds_holding": 0.4},
                "z_aum_weighted_portfolio_pct": float(zh(aum_pct)[j]), "z_avg_portfolio_pct": float(zh(avg_pct)[j]),
                "z_log_total_market_value": 0.0 if mv[i] == 0 else float(zh(np.log1p(mv))[j]),
                "z_n_funds_holding": float(zh(n_hold)[j])}
        row = base(i, "consensus", r_)
        row.update({"n_funds_holding": int(n_hold[i]), "total_market_value": money(mv[i]),
                    "aum_weighted_portfolio_pct": float(aum_pct[i]), "avg_portfolio_pct": float(avg_pct[i]),
                    "consensus_score": float(3.0 * cs[j] + 1.0), "consensus_percentile": pctl(r_),
                    "consensus_rank": r_ + 1, "components_json": json.dumps(comp)})
        rows.append(finish(row, "whale_consensus_score_v1_0", i, 0, null_name=(m == "us" and r_ == 0)))
    boards["consensus"] = rows
    # conviction
    conv = 0.6 + 0.9 * np.abs(rng.standard_normal(len(held))) + 0.3 * zh(avg_pct)
    rows = []
    for r_, j in enumerate(np.argsort(-conv)[:20]):
        i = held[j]
        fund = funds[int(rng.integers(len(funds)))][0]
        mz = float(conv[j] * rng.uniform(1.0, 1.05))
        row = base(i, "conviction", r_)
        row.update({"n_funds_holding": int(n_hold[i]), "ticker_conviction_score": float(conv[j]),
                    "ticker_conviction_percentile": pctl(r_), "ticker_conviction_rank": r_ + 1,
                    "max_fund_conviction_z": mz, "top_conviction_fund": fund,
                    "components_json": json.dumps({"max_fund_conviction_z": mz, "top_conviction_fund": fund})})
        rows.append(finish(row, "whale_conviction_index_v1_0", i, 1, null_name=(m == "us" and r_ in (2, 13))))
    boards["conviction"] = rows
    # crowdedness
    crowd = n_hold[held] / wc["crowd_total"]
    rows = []
    for r_, j in enumerate(np.argsort(-crowd, kind="stable")[:20]):
        i = held[j]
        row = base(i, "crowdedness", r_)
        row.update({"n_funds_holding": int(n_hold[i]), "n_funds_total": wc["crowd_total"],
                    "crowdedness_pct": float(crowd[j]), "crowdedness_quintile": 1, "crowdedness_rank": r_ + 1})
        rows.append(finish(row, "whale_crowdedness_v1_0", i, 2))
    boards["crowdedness"] = rows
    # position delta (linked to the sector board's whale_trend through the same flow)
    flow = W["flow"][held]
    nh = len(held)
    buy = (np.clip(np.round(n_hold[held] * (0.05 + 0.05 * np.tanh(flow))), 0, None) + rng.poisson(0.8, nh)).astype(int)
    sell = np.clip(np.round(n_hold[held] * (0.05 - 0.04 * np.tanh(flow))) + rng.poisson(0.5, nh), 0, None).astype(int)
    if m in ("jp", "hk"):  # live JP/HK deltas come from new disclosures only
        sell[:] = 0
    gross_b = buy * W["shares"][held] * wc["share_frac"] * np.exp(0.6 * rng.standard_normal(nh))
    gross_s = sell * W["shares"][held] * wc["share_frac"] * np.exp(0.6 * rng.standard_normal(nh))
    net = gross_b - gross_s
    dz = 3.0 * zs(np.sign(net) * np.log1p(np.abs(net)))
    rows = []
    for r_, j in enumerate(np.argsort(-dz)[:20]):
        i = held[j]
        row = base(i, "position_delta", r_)
        row.update({"n_funds_buying": int(buy[j]), "n_funds_selling": int(sell[j]), "net_shares_change": money(net[j]),
                    "gross_shares_buying": money(gross_b[j]), "gross_shares_selling": money(-gross_s[j]) + 0.0,
                    "delta_z": float(dz[j]), "delta_rank": r_ + 1, "delta_percentile": pctl(r_)})
        rows.append(finish(row, "whale_position_delta_v1_0", i, 3, null_name=(m == "us" and r_ == 9)))
    boards["position_delta"] = rows
    # network
    degree = np.round((n_hold[held] * rng.uniform(4, 9, nh) + 20) * wc["deg_scale"]).astype(int)
    wdeg = degree * rng.uniform(1.8, 5.0, nh)
    eig = wdeg / np.sqrt((wdeg ** 2).sum())
    comm = rng.integers(0, min(wc["communities"], 6), len(held))
    comm_size = Counter(comm.tolist())
    rows = []
    for r_, j in enumerate(np.argsort(-eig)[:20]):
        i = held[j]
        row = base(i, "network", r_)
        row.update({"degree": int(degree[j]), "weighted_degree": money(wdeg[j]), "eigenvector_centrality": float(eig[j]),
                    "community_id": int(comm[j]), "n_tickers_in_community": int(comm_size[int(comm[j])]),
                    "n_communities": wc["communities"], "modularity": wc["modularity"]})
        rows.append(finish(row, "whale_network_v1_0", i, -80))
    boards["network"] = rows
    # lead-lag predictive (ownership change quarter on quarter)
    occ = np.round(n_hold[held] * np.clip(0.2 + 0.25 * np.tanh(flow) + 0.15 * rng.standard_normal(nh), 0, 1))
    q1 = n_hold[held] - occ
    if m != "us":  # live: most leaders are new disclosures with no prior-quarter holders
        new = rng.random(nh) < 0.6
        q1 = np.where(new, 0, q1)
        occ = n_hold[held] - q1
    q1, occ = q1.astype(int), occ.astype(int)
    pwc = occ * rng.uniform(0.3, 3.0, nh)
    ll = 3.0 * zs(occ + 0.3 * pwc) + 0.5
    rows = []
    for r_, j in enumerate(np.argsort(-ll)[:20]):
        i = held[j]
        row = base(i, "ll_predictive", r_)
        row.update({"n_funds_holding_q": int(n_hold[i]), "n_funds_holding_q_minus_1": int(q1[j]),
                    "owner_count_change": int(occ[j]), "portfolio_weight_change": float(pwc[j]),
                    "ll_score_z": float(ll[j]), "ll_rank": r_ + 1, "ll_percentile": pctl(r_)})
        rows.append(finish(row, "whale_ll_predictive_v1_0", i, 4))
    boards["ll_predictive"] = rows
    return dict(boards=boards, funds=funds)


GATE_REASONS = {
    "publish_tested": ["all gate checks pass", "all gate checks pass; data_depth_caveat: few quarter-on-quarter "
                       "transitions available"],
    "restricted": ["OOS lift not assessable (forward window not yet observed)",
                   "weak in-sample fit; OOS lift not assessable (forward window not yet observed)"],
    "draft": ["in-sample fit unavailable; OOS lift not assessable (forward window not yet observed)",
              "negative OOS lift", "weight stability below 0.50"],
}


def gate_rows(m: str) -> list[dict]:
    rng = rng_for("gates", m)
    signals, n = GATE_SIGNALS[m]
    states, weights = {"us": (["publish_tested", "restricted", "draft"], [0.35, 0.26, 0.39]),
                       "cn": (["publish_tested", "restricted", "draft"], [0.42, 0.16, 0.42]),
                       "jp": (["restricted", "draft"], [0.89, 0.11]),
                       "hk": (["publish_tested", "restricted", "draft"], [0.03, 0.57, 0.40])}[m]
    dates = ([d.isoformat() for d in (date(2026, 6, 30), date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30),
                                      date(2025, 6, 30), date(2025, 3, 31), date(2024, 12, 31))]
             if m in ("us", "cn") else [d.isoformat() for d in trading_days(m, date(2026, 10, 7), 60)][::-1])
    rows = []
    while len(rows) < n:
        sid = signals[len(rows) % len(signals)]
        as_of = dates[(len(rows) // len(signals)) % len(dates)]
        state = str(rng.choice(states, p=weights))
        pool = GATE_REASONS[state] if m != "jp" else [r for r in GATE_REASONS[state] if "negative" not in r
                                                     and "stability" not in r]
        reason = str(rng.choice(pool))
        oos = None
        if state == "publish_tested":
            oos = round(float(rng.normal(2.0, 8.0)), 2)
        elif reason == "negative OOS lift":
            oos = -abs(round(float(rng.normal(12.0, 8.0)), 2))
            reason = f"negative OOS lift ({oos:.1f}%)"
        fit = None if reason.startswith("in-sample fit unavailable") else round(float(rng.uniform(-0.3, 0.9)), 3)
        stability = None if (m != "jp" and fit is None and rng.random() < 0.5) else \
            (1.0 if rng.random() < 0.8 else round(float(rng.uniform(0.8, 1.0)), 3))
        spanning = round(float(rng.uniform(0, 1)), 3) if state == "publish_tested" or rng.random() < 0.15 else None
        rows.append({
            "signal_id": sid, "market": m, "as_of_date": as_of, "publish_state": state, "in_sample_fit": fit,
            "oos_lift_pct": oos, "stability": stability, "spanning_alpha": spanning,
            "sensitivity_test_pass": bool(rng.random() < 0.92), "gate_reason": reason,
        })
    return rows


def whales_payload(W: dict, gate_total: int) -> dict:
    m = W["m"]
    rng = rng_for("whales_meta", m)
    st = W["WH"]
    latest = {"us": "2026-06-30", "cn": "2026年2季度股票投资明细"}.get(m)
    fund_rows = []
    for name, fid in st["funds"]:
        lq = latest or (date(2026, 6, 30) - timedelta(days=int(rng.integers(0, 400)))).isoformat()
        if m == "us":
            quarters, holdings = int(rng.choice([3, 2, 1], p=[0.94, 0.03, 0.03])), int(min(120, rng.integers(40, 200)))
        elif m == "cn":
            quarters, holdings = int(rng.choice([10, 7], p=[0.97, 0.03])), int(rng.integers(150, 720))
        else:
            quarters = int(rng.choice([1, 2, 3], p=[0.88, 0.08, 0.04]))
            holdings = int(rng.choice([1, 2, 3, 5], p=[0.7, 0.15, 0.1, 0.05]))
        fund_rows.append({"market": m, "fund_name": name, "fund_id": fid, "quarters": quarters,
                          "total_holdings": holdings, "latest_quarter": lq})
    fund_rows.sort(key=lambda r: r["fund_name"])
    data = {
        "market": m, "as_of": "2026-10-07", "method": "page_whales_v1",
        "signal_board": {"market": m, "as_of": "2026-10-07", "signals": st["boards"]},
        "signal_gate_status": {"count": gate_total, "gates": gate_rows(m)},
        "funds": {"count": len(fund_rows), "funds": fund_rows},
        "fund_lead_lag": None, "letter_nlp": None,
    }
    if m == "us":  # live: US only; the other markets send null
        ll_funds = []
        for name, _ in st["funds"][:18]:
            nq = int(rng.choice([3, 4, 5, 7, 14, 40, 66, 92]))
            score = float(rng.normal(-0.4, 0.4))
            ll_funds.append({"fund_name": name, "n_quarters_observed": nq,
                             "avg_filing_speed_days": round(float(rng.uniform(26, 46)), 1),
                             "intraday_lead_rank_avg": round(float(rng.uniform(0.1, 0.95)), 2),
                             "leader_score": round(score, 3), "leader_score_z": round((score + 0.4) / 0.4, 2),
                             "data_depth_caveat": f"only {nq} quarters of filing history; leader_score is preliminary"
                             if nq < 8 else None})
        ll_funds.sort(key=lambda r: -r["leader_score"])
        data["fund_lead_lag"] = {"count": len(ll_funds), "funds": ll_funds}
        letters = []
        letter_fund = st["funds"][0][0]
        for year in range(1998, 2026):
            tokens = int(rng.integers(2600, 18000))
            pos, neg = int(tokens * rng.uniform(0.012, 0.025)), int(tokens * rng.uniform(0.006, 0.014))
            unc = int(tokens * rng.uniform(0.006, 0.014))
            fp, fn = float(rng.uniform(0.1, 0.28)), float(rng.uniform(0.05, 0.25))
            letters.append({"fund_name": letter_fund, "letter_date": f"{year}-02-{int(rng.integers(21, 29))}",
                            "letter_type": "annual", "total_tokens": tokens, "n_positive": pos, "n_negative": neg,
                            "n_uncertainty": unc, "sentiment_score": round((pos - neg) / tokens, 4),
                            "uncertainty_intensity": round(unc / tokens, 4), "net_tone": round((pos - neg) / (pos + neg), 3),
                            "lexical_diversity": round(float(rng.uniform(0.21, 0.43)), 3), "finbert_positive": round(fp, 4),
                            "finbert_negative": round(fn, 4), "finbert_neutral": round(1 - fp - fn, 4),
                            "finbert_net_tone": round(fp - fn, 4), "finbert_n_chunks": int(tokens / 240)})
        data["letter_nlp"] = {"count": len(letters), "letters": letters}
    return {"ok": True, "schema_version": "surgeflow.market_whales.v1", "source": "/api/page/whales", "market": m,
            "data": data}


# ---------------------------------------------------------------------------- news (INFERRED shape)
# Live on 2026-10-07 every market answered {"ok": true, "data": {"ok": false, "error": {...}}}, so the success
# shape below is inferred: the envelope follows the error response, the article keys match the articles that
# live notes/daily embeds, and data.coverage / data.methodology follow the keyless /api/news/feed twin.
NEWS_SOURCES = {  # (provider, source_family, publisher, article_type, weight)
    "us": [("benzinga", "vendor_news", "Benzinga", "news", 0.4), ("polygon", "polygon_news", "GlobeNewswire Inc.", "news", 0.3),
           ("fmp", "fmp_stock_news", "Financial Modeling Prep", "stock", 0.3)],
    "cn": [("eastmoney", "tushare_news_eastmoney", "东方财富", "market", 0.45), ("10jqka", "tushare_news_10jqka", "同花顺", "stock", 0.3),
           ("sina", "tushare_news_sina", "新浪财经", "market", 0.25)],
    "jp": [("tdnet", "tdnet_disclosures", "TDnet", "disclosure", 0.45),
           ("yahoo_jp_business", "media_rss_yahoo_jp_business", "Yahoo!ニュース 経済", "media", 0.35),
           ("nhk_business", "media_rss_nhk_business", "NHK ビジネス", "media", 0.2)],
    "hk": [("hkexnews", "hkexnews_titles", "HKEXnews", "disclosure", 0.45),
           ("rthk_hk_finance", "media_rss_rthk_hk_finance", "香港電台 財經", "media", 0.3),
           ("etnet_hk_editor", "media_rss_etnet_hk_editor", "經濟通", "media", 0.25)],
}
NEWS_META = {
    "us": dict(languages=["en"], scored=100.0, total=56000, disclosures=0, source="Vendor and provider stock news",
               family="polygon_news", sentiment="Provider sentiment plus model scoring"),
    "cn": dict(languages=["zh"], scored=90.0, total=73000, disclosures=0, source="Licensed Chinese market news channels",
               family="tushare_major_news", sentiment="Model scoring of the licensed Chinese feed"),
    "jp": dict(languages=["en", "ja"], scored=100.0, total=24700, disclosures=14200, source="TDnet disclosures + business RSS",
               family="tdnet_edinet_rss", sentiment="Model scoring of the implication for the tagged company"),
    "hk": dict(languages=["en", "zh"], scored=100.0, total=6800, disclosures=3300, source="HKEXnews filings + local finance RSS",
               family="hkexnews_titles", sentiment="Model scoring of the implication for the tagged company"),
}
WRAPS = {  # neutral placeholder market-wrap headlines (positive, negative, neutral)
    "us": ("Synthetic wrap: US stocks close higher in the fixture session", "Synthetic wrap: US stocks close lower in the fixture session",
           "Synthetic wrap: US stocks mixed in the fixture session"),
    "cn": ("合成样例：两市指数收涨", "合成样例：两市指数收跌", "合成样例：两市指数窄幅震荡"),
    "jp": ("合成サンプル：日経平均は上昇", "合成サンプル：日経平均は下落", "合成サンプル：東証は小動き"),
    "hk": ("合成樣本：恒指收高", "合成樣本：恒指收低", "合成樣本：恒指窄幅上落"),
}


def news_text(m: str, kind: str, name: str, ret: float, mult: float) -> tuple[str, str]:
    """Placeholder headline + description built from the fixture's own numbers."""
    pct, up = abs(ret) * 100, ret >= 0
    if kind == "wrap":
        t = WRAPS[m][0 if ret >= 0.2 else 1 if ret <= -0.2 else 2]
        return t, t + " (placeholder text, not a real article)."
    if m == "us":
        t = f"Synthetic headline: {name} {'rises' if up else 'falls'} {pct:.1f}% on {mult:.1f}x prior-day turnover"
        return t, t + ". Placeholder text generated from fixture numbers, not a real article."
    if kind == "disclosure":
        t = {"jp": f"{name}：合成サンプルの適時開示", "hk": f"{name} - 合成樣本公告"}[m]
        return t, t
    t = {"cn": f"合成样例：{name}{'上涨' if up else '下跌'}{pct:.1f}%，成交额为前一交易日{mult:.1f}倍",
         "jp": f"合成サンプル：{name}は{pct:.1f}%{'上昇' if up else '下落'}、売買代金は前日比{mult:.1f}倍",
         "hk": f"合成樣本：{name}股價{'升' if up else '跌'}{pct:.1f}%，成交額為前日{mult:.1f}倍"}[m]
    return t, t + "（占位文本）"


def news_articles(W: dict, n_articles: int = 40) -> list[dict]:
    m, F, N = W["m"], W["F"], W["N"]
    rng = rng_for("news", m)
    latest = {"us": utc(2026, 10, 6, 22, 30), "cn": utc(2026, 10, 6, 15, 50)}.get(m, NOW - timedelta(minutes=20))
    srcs = NEWS_SOURCES[m]
    probs = np.array([s[4] for s in srcs])
    weight = np.sqrt(F["market_cap_usd"]) * (1 + 2 * W["surge"])
    weight = weight / weight.sum()
    t = latest
    out = []
    tag_p = {"us": 0.85, "cn": 0.4, "jp": 0.6, "hk": 0.5}[m]
    for a in range(n_articles):
        t = t - timedelta(minutes=int(rng.integers(8, 70)), seconds=int(rng.integers(0, 60)))
        provider, family, publisher, kind, _ = srcs[int(rng.choice(len(srcs), p=probs))]
        idx = []
        if rng.random() < (1.0 if kind == "disclosure" else tag_p):
            idx = [int(i) for i in rng.choice(N, size=int(rng.choice([1, 1, 1, 2, 3])), replace=False, p=weight)]
        if idx:
            i = idx[0]
            chg = float(np.nan_to_num(F["change_pct"][i]))
            base = float(rng.normal(0.05, 0.2)) if kind == "disclosure" else 6.0 * chg + float(rng.normal(0, 0.25))
            title, desc = news_text(m, kind, W["names"][i], chg, float(F["to_yest_mult"][i]))
        else:
            base = float(rng.normal(0.05, 0.3))
            title, desc = news_text(m, "wrap", "", base, 1.0)
        score = float(np.clip(round(base * 10) / 10, -1, 1))
        label = "positive" if score >= 0.2 else "negative" if score <= -0.2 else "neutral"
        tick_list = [W["tickers"][i] for i in idx]
        keywords = (json.dumps([str(x) for x in rng.choice(["markets", "trading ideas", "analyst ratings", "earnings",
                                                            "price target", "technology", "dividends"], size=3, replace=False)])
                    if m == "us" else "[]" if m == "cn" else json.dumps(["ticker_matched" if tick_list else "no_ticker_match"]))
        published = t.strftime("%Y-%m-%d %H:%M:%S") if provider == "fmp" else t.strftime("%Y-%m-%dT%H:%M:%SZ")
        article_id = md5id(m, a, title)
        out.append({
            "article_id": article_id, "published_utc": published, "title": title, "description": desc,
            "publisher_name": publisher, "article_url": "" if provider == "eastmoney" else f"https://example.com/{m}/{provider}/{article_id}",
            "tickers": json.dumps(tick_list, ensure_ascii=False), "ticker_count": len(tick_list), "keywords": keywords,
            "sentiment_score": score, "sentiment_label": label, "provider": provider, "source_family": family,
            "language": {"us": "en", "cn": "zh", "jp": "ja", "hk": "zh"}[m], "article_type": kind,
            "sentiment_available": True, "content_available": not (provider == "polygon" and a % 5 == 0),
        })
    return out


def news_payload(W: dict) -> dict:
    m = W["m"]
    meta = NEWS_META[m]
    articles = W["NEWS"]
    latest = articles[0]["published_utc"][:10]
    data = {
        "ok": True, "market": m, "count": len(articles), "total_matching": meta["total"], "offset": 0,
        "coverage": {"total_articles": meta["total"], "scored_pct": meta["scored"], "disclosures": meta["disclosures"],
                     "media": meta["total"] - meta["disclosures"], "languages": meta["languages"], "latest_date": latest,
                     "scope": "full_market_corpus", "sentiment_latest_date": latest},
        "articles": articles,
        "methodology": {"source": meta["source"], "source_family": meta["family"], "sentiment_available": True,
                        "sentiment_source": meta["sentiment"],
                        "content_license": "Title and description from the provider; full article at article_url.",
                        "note": "Synthetic fixture articles with placeholder text."},
    }
    return {"ok": True, "schema_version": "surgeflow.market_news.v1", "source": "/api/news/feed", "market": m,
            "data": data}


# ---------------------------------------------------------------------------- factor portfolios
# (factor_id, factor_label, factor_name_published, side_displayed, semantic_label, evidence_status) - live values
FACTORS = [
    ("erp", "Market", "ERP", "market excess return", "Market", "official_index_and_governed_risk_free"),
    ("smb", "Size", "SMB_FF3", "long-short pure factor", "Size", "governed_pit"),
    ("hml", "Value", "HML", "long-short pure factor", "Value", "governed_pit"),
    ("wml", "Momentum", "WML", "long-short pure factor", "Momentum", "governed_market_data"),
    ("rmw", "Profitability", "RMW", "long-short pure factor", "Profitability", "governed_pit"),
    ("cma", "Investment", "CMA", "long-short pure factor", "Investment", "governed_pit_assets"),
    ("liq", "Liquidity", "LIQ", "long-short pure factor", "Liquidity", "governed_turnover_history"),
]
# Live on 2026-10-07 every factor in every market was "blocked" (no returns, no holdings). The fixture publishes
# most factors so the notebooks have return series to analyse, and keeps HK fully blocked like live.
FP_BLOCKED = {"us": {"liq"}, "cn": {"cma", "liq"}, "jp": {"liq"}, "hk": {f[0] for f in FACTORS}}
GATE_REASON = {
    "base": "correlation_triangle_not_tested; stock_residual_diagnostics_not_tested",
    "weak": "correlation_triangle_not_tested; stock_residual_diagnostics_not_tested; premium_not_significant_5pct; "
            "spanning_alpha_not_significant_5pct; factor_redundant_5pct",
    "short": "factor_sample_below_252; premium_hac_not_tested; spanning_not_tested; correlation_triangle_not_tested; "
             "stock_residual_diagnostics_not_tested",
}
FACTOR_GATE = {"erp": "base", "smb": "base", "hml": "weak", "wml": "base", "rmw": "weak", "cma": "short", "liq": "short"}
FP_CORR = np.array([  # modest cross-factor correlations (erp, smb, hml, wml, rmw, cma, liq)
    [1.00, 0.20, -0.05, -0.10, -0.15, -0.20, 0.15],
    [0.20, 1.00, 0.15, -0.10, -0.25, 0.05, 0.35],
    [-0.05, 0.15, 1.00, -0.35, -0.10, 0.40, 0.10],
    [-0.10, -0.10, -0.35, 1.00, 0.15, -0.10, -0.05],
    [-0.15, -0.25, -0.10, 0.15, 1.00, 0.05, -0.15],
    [-0.20, 0.05, 0.40, -0.10, 0.05, 1.00, 0.05],
    [0.15, 0.35, 0.10, -0.05, -0.15, 0.05, 1.00],
])
FP_VOL = np.array([0.0105, 0.0050, 0.0048, 0.0068, 0.0038, 0.0034, 0.0042])
FP_MEAN = np.array([0.00040, 0.00002, 0.00008, 0.00030, 0.00018, 0.00006, 0.00010])
NULL_STATS = {"n_obs": 0, "vol_annual": None, "sharpe": None, "max_dd": None, "var_95_252d": None,
              "es_95_252d": None, "mean_annual": None}


def series_stats(r: np.ndarray) -> dict:
    wealth = np.cumprod(1 + r)
    dd = wealth / np.maximum.accumulate(wealth) - 1
    q = np.quantile(r, 0.05)
    vol = float(r.std(ddof=1) * math.sqrt(252))
    mean = float(r.mean() * 252)
    return {"n_obs": int(len(r)), "vol_annual": round(vol, 4), "sharpe": round(mean / vol, 4) if vol else None,
            "max_dd": round(float(dd.min()), 4), "var_95_252d": round(float(-q), 4),
            "es_95_252d": round(float(-r[r <= q].mean()), 4), "mean_annual": round(mean, 4)}


def fp_payload(W: dict) -> dict:
    m, cfg, F, N = W["m"], W["cfg"], W["F"], W["N"]
    rng = rng_for("factors", m)
    days = trading_days(m, date.fromisoformat(cfg["eod"]), 252)
    chol = np.linalg.cholesky(FP_CORR)
    regime = np.zeros(252)
    for t in range(1, 252):  # slow volatility regime -> fat tails and clustering
        regime[t] = 0.94 * regime[t - 1] + 0.12 * rng.standard_normal()
    shocks = rng.standard_t(5, (252, 7)) / math.sqrt(5 / 3) @ chol.T
    scale = {"us": 1.0, "cn": 1.15, "jp": 1.05, "hk": 1.25}[m]
    R = FP_MEAN + shocks * FP_VOL * scale * np.exp(regime)[:, None]
    blocked = FP_BLOCKED[m]
    cap = F["market_cap"]
    signals = {"smb": (W["log_cap"], "low"), "hml": (F["bp"], "high"), "wml": (F["ret_252d"] - F["ret_20d"], "high"),
               "rmw": (F["profit_margin"], "high"), "cma": (F["revenue_growth"], "low"),
               "liq": (-np.log(F["turnover_ratio"]), "high")}
    factors, ready_ids, ready_R = [], [], []
    for j, (fid, label, published, side, semantic, evidence) in enumerate(FACTORS):
        ready = fid not in blocked
        rec = {"factor_id": fid, "factor_label": label, "factor_name_published": published, "side_displayed": side,
               "effective_sign": 1, "semantic_label": semantic, "publish_state": "published" if ready else "blocked",
               "evidence_status": evidence, "gate_reason": None if ready else GATE_REASON[FACTOR_GATE[fid]],
               "agreement_score": round(float(rng.uniform(0.62, 0.93)), 3) if ready else None,
               "is_risk_ready": ready, "risk_ready_reason": None if ready else "factor_withheld"}
        if not ready:
            rec.update({"n_holdings_active_leg": 0, "holdings_as_of": None, "holdings_weighting": None,
                        "holdings_preview_count": 0, "holdings_complete": True, "benchmark_id": None,
                        "benchmark_name": None, "constituent_source": None, "return_construction": None,
                        "stats": dict(NULL_STATS),
                        "holdings_metrics": {"ep_mcap_weighted": None, "dy_mcap_weighted": None, "tot_market_cap": 0.0,
                                             "n_constituents_total": 0, "n_constituents_with_mcap": 0,
                                             "n_constituents_with_ep": None, "n_constituents_with_dy": None},
                        "top_holdings": [], "return_series": [], "distribution_series": []})
            factors.append(rec)
            continue
        r = R[:, j]
        ready_ids.append(fid)
        ready_R.append(r)
        if fid == "erp":
            idx = np.argsort(-cap)[: N // 2]
            w = cap[idx] / cap[idx].sum()
            holdings = [{"leg": "index", "ticker": W["tickers"][i], "name": W["names"][i], "sector": W["sectors"][i],
                         "market_cap": money(cap[i]), "latest_price": float(F["price"][i]), "weight": round(float(w[k]), 6),
                         "leg_weight": round(float(w[k]), 6), "signal_value": None, "weight_source": "index_float_cap"}
                        for k, i in enumerate(idx[:16])]
            members, n_leg = idx, len(idx)
            extra = {"benchmark_id": cfg["benchmark"][0], "benchmark_name": cfg["benchmark"][1],
                     "constituent_source": "official_index_constituents",
                     "return_construction": "index_total_return_minus_risk_free", "holdings_weighting": "index_weight"}
        else:
            sigv, long_side = signals[fid]
            ok = np.where(np.isfinite(sigv))[0]
            n_leg = max(10, int(round(len(ok) * 0.2)))
            ranked = ok[np.argsort(sigv[ok])]
            low, high = ranked[:n_leg], ranked[::-1][:n_leg]
            long_leg, short_leg = (low, high) if long_side == "low" else (high, low)
            holdings = []
            for leg, legidx, sgn in (("long", long_leg, 1), ("short", short_leg, -1)):
                for i in legidx[:8]:
                    holdings.append({"leg": leg, "ticker": W["tickers"][i], "name": W["names"][i],
                                     "sector": W["sectors"][i], "market_cap": money(cap[i]),
                                     "latest_price": float(F["price"][i]), "weight": round(sgn * 0.5 / n_leg, 6),
                                     "leg_weight": round(1 / n_leg, 6), "signal_value": num(sigv[i]),
                                     "weight_source": "equal_weight_leg"})
            members = np.concatenate([long_leg, short_leg])
            extra = {"benchmark_id": None, "benchmark_name": None, "constituent_source": "governed_pit_universe",
                     "return_construction": "long_short_equal_weight_legs", "holdings_weighting": "equal_weight_legs"}
        epv, dyv, capm = F["ep"][members], F["dividend_yield"][members], cap[members]
        ok_ep, ok_dy = np.isfinite(epv), np.isfinite(dyv)
        rec.update({
            "n_holdings_active_leg": int(n_leg), "holdings_as_of": cfg["eod"],
            "holdings_weighting": extra.pop("holdings_weighting"), "holdings_preview_count": len(holdings),
            "holdings_complete": len(holdings) >= len(members), **extra, "stats": series_stats(r),
            "holdings_metrics": {
                "ep_mcap_weighted": round(float(np.sum(epv[ok_ep] * capm[ok_ep]) / np.sum(capm[ok_ep])), 4),
                "dy_mcap_weighted": round(float(np.sum(dyv[ok_dy] * capm[ok_dy]) / np.sum(capm[ok_dy])), 4)
                if ok_dy.any() else None,
                "tot_market_cap": money(capm.sum()), "n_constituents_total": int(len(members)),
                "n_constituents_with_mcap": int(len(members)), "n_constituents_with_ep": int(ok_ep.sum()),
                "n_constituents_with_dy": int(ok_dy.sum())},
            "top_holdings": holdings,
            "return_series": [{"date": d.isoformat(), "ret": round(float(x), 5)} for d, x in zip(days, r)],
            "distribution_series": [],
        })
        factors.append(rec)
    if ready_R:
        RR = np.column_stack(ready_R)
        agg = RR.mean(axis=1)
        corr = np.corrcoef(RR.T)
        aggregate = {"equal_weight_stats": series_stats(agg),
                     "factor_correlation": {"factor_ids": ready_ids,
                                            "values": [[round(float(v), 4) for v in row] for row in corr]}
                     if len(ready_ids) >= 2 else None,
                     "n_aligned_dates": 252, "correlation_start": days[0].isoformat(),
                     "correlation_as_of": days[-1].isoformat(),
                     "return_series": [{"date": d.isoformat(), "ret": round(float(x), 5)} for d, x in zip(days, agg)]}
    else:  # the live state on 2026-10-07
        aggregate = {"equal_weight_stats": dict(NULL_STATS), "factor_correlation": None, "n_aligned_dates": 0,
                     "correlation_start": None, "correlation_as_of": None, "return_series": []}
    hold_total = sum(len(f["top_holdings"]) for f in factors)
    data = {
        "market": m, "release_id": "factor_daily_20261007t021508334190z",
        "factor_contract_sha256": hexid("factor-contract-fixture", n=64),
        "contract_factors": [f[0] for f in FACTORS],
        "research_passport": {
            "passport_schema_version": "1.0", "research_case_id": hexid("case", m, n=64),
            "short_id": f"SF-{hexid('case', m, n=6).upper()}", "research_chain_id": f"CH-{hexid('chain', m, n=10).upper()}",
            "chain_position": "portfolio", "source_research_case_id": None, "parent_research_case_id": None,
            "surface": "portfolio", "market": m, "factor_definitions": [],
            "universe_version": "factor_candidate_complete_case_v1_20260822", "methodology_version": None,
            "backtest_engine_version": None,
            "portfolio_membership_version": "factor_membership_v3p2 atomic snapshot + index constituents (ERP display)",
            "publication_gate_version": "factor_operating_status_v1 atomic admission",
            "ranking_variable": "canonical factor signal; ERP primary index", "portfolio_cutoff": None,
            "weighting_method": "ERP index-weighted; non-ERP 50/50 long-short with equal-weighted legs",
            "rebalance_rule": "factor-specific canonical rebalance calendar", "benchmark_id": cfg["benchmark"][0],
            "cost_model": {"gross_or_net": "gross", "cost_model_id": "none", "cost_model_version": "pure_factor_no_cost",
                           "buy_cost_bps": None, "sell_cost_bps": None, "market_impact_model": None, "tax_model": None},
            "test_type": "display-only canonical pure-factor portfolio",
            "point_in_time_status": "latest published membership snapshot",
            "publication_status": "only pointer-selected published factors carry returns and holdings",
            "data_cutoff": None, "generated_at": None, "freshness_status": None,
            "surface_oos_status": "not_applicable", "source_evidence_oos_status": "in_sample",
        },
        "as_of": cfg["eod"] if ready_R else None, "n_active": len(ready_ids), "n_risk_ready": len(ready_ids),
        "factors": factors, "aggregate": aggregate, "word_cloud": [],
        "narrative_coverage": {"holdings_total": hold_total, "holdings_with_narrative": 0, "coverage_pct": 0.0},
        "raw_survivors_summary": sorted(
            [{"factor_name": f[2].split("_")[0], "publish_state": "published" if f[0] not in blocked else "blocked",
              "evidence_status": f[5], "effective_sign": 1, "semantic_label": f[4]} for f in FACTORS],
            key=lambda r: r["factor_name"]),
        "disclosure": "ERP is the market excess return over the official index. SMB to LIQ are built from one "
                      "point-in-time ticker universe as +50% long / -50% short legs with equal weights. Gate state "
                      "is disclosed per factor and is not used as a row filter. Synthetic fixture values.",
    }
    return {"ok": True, "schema_version": "surgeflow.factor_portfolios.v1", "source": "/api/portfolio/factor-portfolios",
            "market": m, "note": NOTE, "data": {"ok": True, "data": data}}


# ---------------------------------------------------------------------------- summary (INFERRED shape)
# Live GET /api/v1/summary answered HTTP 500 on 2026-10-07, so this whole payload keeps the shape inferred
# from the keyless /api/summary twin and the website JavaScript. Nothing here is confirmed by a live v1 body.
def long_meta(m: str, start: date, n: int) -> dict:
    cfg = CFG[m]
    pit = m == "cn"
    return {
        "anchor_date": cfg["eod"], "anchor_drift_pct": {"us": -0.53, "cn": -0.10, "jp": 0.21, "hk": -0.34}[m],
        "available_years": 2.52, "currency": cfg["currency"], "current_proxy_value_pct": 0.0 if pit else 100.0,
        "current_reconciliation_name_coverage_pct": 100.0, "current_reconciliation_value_coverage_pct": 100.0,
        "dated_share_name_coverage_pct": 100.0, "dated_share_value_coverage_pct": 100.0,
        "evidence_contract_version": "market_cap_pit_evidence_v9", "history_state": "multi_year",
        "information_pit": pit, "information_pit_value_pct": 100.0 if pit else 0.0, "latest_covered_tickers": n,
        "latest_name_coverage_pct": 100.0, "latest_universe_tickers": n, "latest_value_coverage_pct": 100.0,
        "methodology_version": "chain_linked_market_cap_monthly_v4", "period_dated_value_pct": 0.0,
        "price_basis": "governed local-currency close; bounded normalized-price bridge when required",
        "public_history_eligible": True,
        "share_basis": "daily reported shares available with the trading session" if pit
        else "period-dated shares plus current class-level overlays",
        "share_evidence_state": "strict_pit" if pit else "mixed_pit", "source_end_date": cfg["eod"],
        "source_kind": "governed_market_cap_history",
        "source_mix": "Synthetic fixture: latest value-weighted evidence mix.",
        "source_start_date": start.isoformat(), "unit_match_ticker_pct": 100.0, "unit_match_value_pct": 100.0,
        "unit_reconciliation_ratio": 1.0,
        "universe_basis": "latest tier2-eligible factor universe; current-universe comparable series",
        "withheld_reason": None,
    }


def summary_payload(worlds: dict) -> dict:
    rng = rng_for("summary")
    markets = []
    totals = Counter()
    for m in MARKETS:
        W = worlds[m]
        cfg, F, N = W["cfg"], W["F"], W["N"]
        eligible, latest_valid, distinct = round(N * 1.22), round(N * 1.35), round(N * 1.6)
        turnover = float(np.nansum(F["turnover"]))
        cap_sum = float(np.sum(F["market_cap"]))
        eod = date.fromisoformat(cfg["eod"])
        days = trading_days(m, eod, 30)
        level = np.exp(np.cumsum(rng.normal(0.0004, 0.009, 30)))
        level = level / level[-1]
        mch = [{"date": d.isoformat(), "total_market_cap_local": money(cap_sum * level[k]),
                "total_turnover_local": money(turnover * float(np.exp(rng.normal(0, 0.18))) if k < 29 else turnover),
                "currency": cfg["currency"], "coverage_pct": round(100 * (N - 3) / eligible, 2), "covered_tickers": N - 3,
                "universe_tickers": eligible, "max_price_age_days": 7,
                "methodology_version": "current_validated_shares_constant_v1",
                "price_basis": "latest normalized close on or before each session; max 7 calendar days",
                "share_basis": "latest validated shares held constant across the displayed window"}
               for k, d in enumerate(days)]
        months, d = [], date(2024, 3, 31)
        while d < eod:
            months.append(d)
            nxt = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
            d = date(nxt.year + (nxt.month // 12), nxt.month % 12 + 1, 1) - timedelta(days=1)
        months.append(eod)
        steps = rng.normal(0.006, 0.045, len(months))
        steps[0] = 0.0
        cum = np.cumsum(steps)
        chain = cap_sum * np.exp(cum - cum[-1])
        long_hist = []
        for k, d in enumerate(months):
            cov = min(100.0, 60 + 40 * k / (len(months) - 1))
            long_hist.append({"date": d.isoformat(), "chain_linked_market_cap": money(chain[k]),
                              "cumulative_log_change_pct": round(100 * float(cum[k]), 4),
                              "period_log_change_pct": round(100 * float(steps[k]), 4),
                              "covered_tickers": int(round(N * cov / 100)), "universe_tickers": N,
                              "name_coverage_pct": round(cov, 2), "value_coverage_pct": round(min(100.0, cov + 15), 2),
                              "overlap_tickers": 0 if k == 0 else int(round(N * cov / 100 * 0.97)),
                              "overlap_value_coverage_pct": None if k == 0 else round(float(rng.uniform(96, 99.9)), 2),
                              "transition_basis": "initial" if k == 0 else
                              ("pit_market_cap" if m in ("cn", "hk") else "normalized_price_bridge")})
        big = np.where(F["market_cap_usd"] > 1e9)[0]
        allr = np.arange(N)
        leaders = {}
        for key, char, desc, pool, vals, rev in (
            ("hml", "bp", "Highest book/price (B/M proxy, >$1B)", big, F["bp"], True),
            ("rmw", "profit_margin", "Highest profit margin (>$1B). Proxy for canonical EBIT/equity.", big,
             F["profit_margin"], True),
            ("smb", "market_cap", "Smallest market cap in screen universe", allr, F["market_cap"], False),
            ("wml", "momentum_12m1m", "Highest 12m-1m momentum (>$1B)", big, (1 + F["ret_252d"]) / (1 + F["ret_20d"]) - 1, True),
        ):
            ok = [i for i in pool if math.isfinite(vals[i])]
            ranked = sorted(ok, key=lambda i: vals[i], reverse=rev)[:3]
            leaders[key] = {"characteristic": char, "description": desc,
                            "leaders": [{"ticker": W["tickers"][i], "name": W["names"][i],
                                         "characteristic_value": round(float(vals[i]), 4)} for i in ranked]}
        populated = m in ("cn", "hk")
        premiums = {}
        if populated:
            for fac in ("investment", "liquidity", "market", "momentum", "profitability", "size", "value"):
                roll = float(rng.normal(0.001, 0.004))
                premiums[fac] = {"factor": fac.upper(), "date": cfg["eod"], "daily_premium": round(float(rng.normal(0.0002, 0.0012)), 6),
                                 "display_premium": round(roll, 6), "display_window": "21D", "rolling_21d_premium": round(roll, 6),
                                 "rolling_21d_n": 21, "monthly_premium": None, "n_obs": N, "n_long": None, "n_short": None,
                                 "definition": "consistent_pure_factor_realised_return",
                                 "interpretation": "consistent_pure_style_return", "source_factor_name": fac.upper()}
            fpm = {"calendar_last_completed_session": cfg["eod"], "data_through_session": cfg["eod"],
                   "definition": "consistent_pure_factor_realised_return", "error_rate_label": "Not measured",
                   "inference_status": "unsupported_not_estimated", "input_lag_sessions": 0,
                   "input_through_session": cfg["eod"],
                   "message": "Pure-factor realised returns summed over 21 sessions. Not expected premia.",
                   "reason_code": None, "source": "factor_returns_consistent_daily_v1", "status": "available",
                   "window": "21 sessions, arithmetic sum of daily pure-factor returns"}
        else:
            fpm = {"status": "unavailable", "publication_status": "withheld",
                   "policy_version": "overview_factor_premium_containment_v1",
                   "reason_code": "fresh_same_definition_not_verified",
                   "message": "Factor figures are withheld while freshness and definitions are reviewed.",
                   "legacy_source": "stock_data.factor_returns_v1", "replacement_source": None,
                   "freshness_status": "not_verified", "expected_session_date": None, "model_changed": False,
                   "source_observation_dates": [], "last_observed_date": None}
        macro = W["MACRO_CYCLE"]
        ex = cfg["excl"]
        adr, non_eq, no_price = (int(round(N * ex[k])) for k in ("adr", "non_equity", "no_price"))
        surge = int(np.sum(F["tv10"] > 1))
        markets.append({
            "market": m, "label": cfg["label"], "as_of_date": cfg["eod"], "eod_session_date": cfg["eod"],
            "eod_session_complete": True, "eod_session_disclosures": [], "ticker_count": eligible,
            "screen_eligible_tickers": eligible, "institutional_count": N, "institutional_tickers": N,
            "latest_valid_eod_tickers": latest_valid, "total_distinct_eod_tickers": distinct, "surge_count": surge,
            "accel_count": surge, "surge_definition": "turnover_today_gt_turnover_ma10",
            "above_ma10_count": int(np.sum(F["ma10_excess"] > 0)), "microcap_count": 0,
            "avg_change_pct": round(float(np.nanmean(F["change_pct"])), 4), "total_turnover": int(round(turnover)),
            "ladder_nesting_ok": True, "ladder_nesting_violations": [],
            "universe": {"tracked_count": N + adr + non_eq + no_price, "screen_eligible_count": N,
                         "exclusions": {"adr": adr, "non_equity": non_eq, "no_price": no_price, "no_fundamentals": 0}},
            "factor_leaders": leaders, "factor_premiums": premiums, "factor_premiums_meta": fpm,
            "macro_cycle": {"leading": macro[0], "coincident": macro[1], "lagging": macro[2], "date": "2026-09-30",
                            "methodology_version": "yellow_macro_regime_v1_0"},
            "market_cap_history": mch, "market_cap_long_history": long_hist,
            "market_cap_long_meta": long_meta(m, months[0], N),
        })
        totals["screen_eligible_tickers"] += eligible
        totals["institutional_tickers"] += N
        totals["latest_valid_eod_tickers"] += latest_valid
        totals["total_distinct_eod_tickers"] += distinct
    data = {
        "timestamp": "2026-10-07T05:10:22.796374+00:00",
        "fx_rates": {"cnyPerUsd": CFG["cn"]["fx"], "gbpPerUsd": 0.7514, "hkdPerUsd": CFG["hk"]["fx"],
                     "inrPerUsd": 88.42, "jpyPerUsd": CFG["jp"]["fx"], "krwPerUsd": 1398.6, "twdPerUsd": 30.41},
        "totals": {"markets": 4, **{k: totals[k] for k in ("screen_eligible_tickers", "institutional_tickers",
                                                           "latest_valid_eod_tickers", "total_distinct_eod_tickers")},
                   "ladder_nesting_ok": True, "ladder_nesting_violations": {}, "session_policy": "session_completeness.v1"},
        "factor_premiums_meta": {"status": "unavailable", "publication_status": "withheld",
                                 "policy_version": "overview_factor_premium_containment_v1",
                                 "reason_code": "fresh_same_definition_not_verified",
                                 "message": "Cross-market factor figures are withheld until every market passes the "
                                            "same-definition check.",
                                 "legacy_source": None, "replacement_source": None, "freshness_status": "not_verified",
                                 "expected_session_date": None, "model_changed": False},
        "factor_leaders_methodology": {
            "type": "characteristic_leaders",
            "universe": "Institutional-filtered screen universe (same rows as the default screen)",
            "min_market_cap_filter": "$1B USD for HML/WML/RMW to ensure meaningful names.",
            "note": "Characteristic-ranked leaders from the screen universe, not factor portfolio holdings.",
            "hml": "Ranked by book/price (descending).", "rmw": "Ranked by profit margin (descending).",
            "smb": "Ranked by market cap (ascending).", "wml": "Ranked by 12m-1m momentum (descending).",
        },
        "markets": markets,
    }
    return {"ok": True, "schema_version": "surgeflow.public_api.v1", "data": data}


# ---------------------------------------------------------------------------- AI ratings + grade book (US)
# Live on 2026-10-07 the latest council checkpoint was a month old, so today's grade-book openers were all
# rejected as stale. The fixture keeps that situation (with its own synthetic dates and numbers).
CKPT_ID = "flow_capital_live_v22_20260904T0215"
CKPT_TIME = utc(2026, 9, 4, 2, 15)
CKPT_SESSION = "2026-09-03"
CORE_LENSES = ["fundamental", "factor", "technical", "sentiment"]
ALL_LENSES = ["factor", "fundamental", "technical", "sentiment", "macro", "risk"]
PERSONAS = ["factor_analyst", "fundamental_analyst", "macro_analyst", "risk_manager", "sentiment_analyst",
            "technical_analyst"]
COMPOSITES = [73.5, 47.25, 41.5, 36.75, 31.0, 27.5, 22.25, 19.5, 15.0, 12.25, 10.5, 8.0]  # rank order
FLAGS = {0: "long", 7: "short", 8: "short", 9: "short", 10: "short", 11: "short"}
STOPPED = 11  # this short breached its hard stop
SCORE_RULE = ">70 LONG; <30 SHORT; 30..70 HOLD"
ZONE_FORMULA = "day_low + (day_high - day_low) / 3"


def lens_comment(lens: str, ticker: str, score) -> str:
    if score is None:
        return f"Placeholder: no {lens} evidence was routed for {ticker} in this synthetic checkpoint, so no score."
    tone = "supportive" if score >= 60 else "mixed" if score >= 35 else "cautious"
    return f"Placeholder {lens} note for {ticker}: synthetic score {score:.0f}/100, {tone} read."


def core_scores(target: float, rng) -> list[float]:
    """Four integer scores whose mean is exactly target (composite = mean of the four core lenses)."""
    for _ in range(1000):
        s = [float(np.clip(round(target + rng.normal(0, 14)), 0, 100)) for _ in range(3)]
        last = 4 * target - sum(s)
        if 0 <= last <= 100 and last == round(last):
            return s + [float(last)]
    raise RuntimeError("could not hit composite target")


def ai_ratings_payload(W: dict) -> tuple[dict, list[dict]]:
    rng = rng_for("ai_ratings")
    F = W["F"]
    # hotlist names: smaller US caps with heavy attention (live: micro and small caps)
    pool = [int(i) for i in W["by_cap"][400:] if W["lat"][i][5] > 0.0 and W["F"]["price"][i] < 30]
    picks = [int(i) for i in rng.choice(pool, size=len(COMPOSITES), replace=False)]
    names = []
    for k, (i, target) in enumerate(zip(picks, COMPOSITES)):
        tk = W["tickers"][i]
        scores = dict(zip(CORE_LENSES, core_scores(target, rng)))
        if k < 5:  # the top five also carry the macro and risk seats, mostly without a score
            scores["risk"] = 38.0 if k == 3 else None
            scores["macro"] = 35.0 if k == 3 else None
        lens_order = [str(x) for x in rng.permutation(list(scores))]
        direction = FLAGS.get(k)
        # live: a seat can carry a score without a comment (a zero technical score, most seats on the shorts)
        silent = {lens for lens, v in scores.items() if v == 0.0 and lens == "technical"}
        if direction == "short":
            silent |= {"sentiment", "fundamental", "technical"}
        per = {lens: {"score": scores[lens], "comment": None if lens in silent else lens_comment(lens, tk, scores[lens])}
               for lens in lens_order}
        ranked = sorted([(lens, s) for lens, s in scores.items() if s is not None], key=lambda x: -x[1])
        caution = sorted(scores.items(), key=lambda x: (-1 if x[1] is None else x[1]))[:3]
        cur = float(F["price"][i])
        seen = direction != "short"
        first = utc(2026, 9, 3, 13, 31) + timedelta(minutes=int(rng.integers(0, 260)), seconds=int(rng.integers(0, 60)))
        last = min(first + timedelta(minutes=int(rng.integers(20, 200))), utc(2026, 9, 3, 19, 55, 38))
        if direction:
            move = 0.3 if k == STOPPED else float(rng.normal(-0.15 if direction == "short" else 0.08, 0.12))
            anchor = round(cur / (1 + move), 2)
            ret = (cur / anchor - 1) * 100 if direction == "long" else (1 - cur / anchor) * 100
            state = "stopped_out" if ret <= -8 else "working"
            stop = {"state": state, "stop_hit": state == "stopped_out", "hard_stop_pct": -8.0, "warning_pct": -5.0,
                    "stop_price": round(anchor * (0.92 if direction == "long" else 1.08), 4),
                    "message": f"Paper stop hit: direction-adjusted return is {ret:.2f}%, below the -8% guardrail."
                    if state == "stopped_out" else "Paper stop not hit."}
            return_since = {"anchor_close": anchor, "anchor_date": CKPT_SESSION, "return_since_pct": round(ret, 2),
                            "current_price": cur, "current_source": "live", "anchor_status": "anchored",
                            "direction": direction}
            ret_anchor = {"price": anchor, "date": CKPT_SESSION, "status": "anchored"}
        else:
            stop = {"state": "watch_only", "stop_hit": False, "hard_stop_pct": -8.0, "warning_pct": -5.0,
                    "message": "Watch only: not in the paper long/short book, so no stop applies."}
            return_since, ret_anchor = None, {"price": None, "date": None, "status": None}
        summary = (f"Placeholder summary for {tk}: synthetic composite {target:g}; strongest seat "
                   f"{ranked[0][0]}, most cautious seat {caution[0][0]}.")
        names.append({
            "ticker": tk, "composite_score": target, "in_top5": k < 5, "duration_on_list_days": int(rng.integers(1, 5)),
            "headline_comment": summary, "per_analyst": per, "rank": k + 1, "long": direction == "long",
            "short": direction == "short", "return_since": return_since,
            "pick_ledger": {
                "pick_id": f"{CKPT_ID}:{tk}", "checkpoint_id": CKPT_ID, "picked_at": iso(CKPT_TIME),
                "session_date": CKPT_SESSION, "direction": direction or "watch",
                "hotlist_first_seen_at": iso(first) if seen else None,
                "hotlist_last_seen_at": iso(last) if seen else None,
                "hotlist_snapshot_minutes": int(rng.integers(15, 90)) if seen else None,
                "best_hotlist_rank": int(rng.integers(300, 2000)) if seen else None,
                "entry_mark": {"price": round(cur * float(np.exp(rng.normal(-0.05, 0.1))), 4) if seen else None,
                               "snapshot_ts": iso(last) if seen else None,
                               "rank": int(rng.integers(800, 2300)) if seen else None,
                               "projected_yest": round(float(rng.uniform(2.5, 18)), 6) if seen else None,
                               "intraday_return_pct": round(float(rng.uniform(4, 18)), 4) if seen else None,
                               "source": "nearest_hotlist_snapshot"},
                "return_anchor": ret_anchor, "stop": stop,
                "decision": {"direction": f"paper {direction}" if direction else "watch only", "summary": summary,
                             "strongest_agents": [{"agent": a, "score": s, "comment": lens_comment(a, tk, s)} for a, s in ranked[:3]],
                             "caution_agents": [{"agent": a, "score": s, "comment": lens_comment(a, tk, s)} for a, s in caution]},
                "reflection": ("Placeholder reflection: the paper leg breached its hard stop; review the thesis "
                               "against the caution seats.") if stop["state"] == "stopped_out" else None,
            },
        })
    stop_reflections = [{"ticker": n["ticker"], "direction": n["return_since"]["direction"],
                         "return_since_pct": n["return_since"]["return_since_pct"], "picked_at": iso(CKPT_TIME),
                         "message": "Placeholder: stop-loss review required because the paper leg breached the hard "
                                    "stop; compare the thesis with the caution seats before the next revision."}
                        for n in names if n["pick_ledger"]["stop"]["state"] == "stopped_out"]
    data = {
        "checkpoint_id": CKPT_ID, "checkpoint_time": iso(CKPT_TIME), "checkpoint_index": 2,
        "as_of_date": CKPT_SESSION, "market": "us", "decision_session_date": CKPT_SESSION,
        "hotlist_size": len(names), "names": names, "top5": [n["ticker"] for n in names[:5]],
        "left_convictions": [], "stop_reflections": stop_reflections, "analysts": list(ALL_LENSES),
        "source": "panel_tables",
    }
    payload = {"ok": True, "schema_version": "surgeflow.ai_ratings.v1", "source": "/api/fund/hotlist-checkpoint",
               "market": "us", "note": NOTE, "data": data}
    return payload, names


def session_bar(prev_close: float, sigma: float, rng) -> tuple[float, float, float, float]:
    """(high, low, close, observed price at ~19:56 UTC) for one US session."""
    open_ = prev_close * math.exp(rng.normal(0, sigma * 0.3))
    close = open_ * math.exp(rng.normal(0, sigma))
    high = max(open_, close) * math.exp(abs(rng.normal(0, sigma * 0.5)))
    low = min(open_, close) * math.exp(-abs(rng.normal(0, sigma * 0.5)))
    observed = min(max(close * math.exp(rng.normal(0, sigma * 0.08)), low), high)
    return high, low, close, observed


def price2(x: float) -> float:
    return round(x, 2) if x >= 1 else round(x, 4)


def gates_block(side: str, grade: date, zone: float, observed: float, checkpoint: str, council: str,
                fresh: bool = True, reviewed: int = 6, rating_schema: str = "flow_capital_council_rating_v1_0",
                review_date: date | None = None) -> dict:
    personas = PERSONAS if reviewed == 6 else [p for p in PERSONAS if p != "macro_analyst"]
    failures = [] if reviewed == 6 else [f"persona_set={','.join(personas)};expected={','.join(PERSONAS)}"]
    g = {
        "g1_strict_grade": True, "side": side, "score_rule": SCORE_RULE, "g2_six_promoted_reviews": reviewed == 6,
        "agents_reviewed": reviewed if reviewed == 6 else 4, "agents_expected": 6,
        "g3_rationale_contract": not failures, "g3_warn_only": True,
        "rationale_contract": {"promoted_review_count": len(personas), "personas": personas, "failures": failures},
        "review_checkpoint": checkpoint, "council_contract_version": council, "rating_schema_version": rating_schema,
        "g4_review_fresh": fresh, "review_date": (review_date or grade).isoformat(),
        "freshness_floor": prev_trading("us", grade).isoformat(), "g5_drop_out_zone_current": fresh,
        "drop_out_zone": zone, "drop_out_zone_date": grade.isoformat(), "drop_out_observed_price": observed,
        "exit_rule": "Drop Out Zone only", "drop_out_formula": ZONE_FORMULA,
    }
    if not fresh:
        g["g6_no_active_risk_veto"] = True  # live: only today's opener decisions carry g6
    g["g3_warnings"] = [f"six-area rationale contract (warn-only): {f}" for f in failures]
    return g


def grade_book_payload(W: dict, rated: list[dict]) -> dict:
    rng = rng_for("grade_book")
    F = W["F"]
    days = trading_between("us", date(2026, 8, 3), date(2026, 8, 31))
    pool = [int(i) for i in W["by_cap"][:700]]
    rows = []
    for n in range(80):
        side = "LONG" if n % 2 == 0 else "SHORT"
        i = int(rng.choice(pool))
        grade = days[int(rng.integers(len(days)))]
        score = float(rng.uniform(70.2, 88.5)) if side == "LONG" else float(rng.uniform(8.5, 29.8))
        sigma = 1.6 * float(F["daily"][i])
        entry = float(F["price"][i]) * math.exp(rng.normal(-0.02, 0.12))
        while True:  # the opener needs the same-session observed price at or above the Drop Out Zone
            h0, l0, c0, o0 = session_bar(entry, sigma, rng)
            zone0 = l0 + (h0 - l0) / 3
            if o0 >= zone0:
                break
        prices, d, cur = [c0], grade, c0
        exit_bar = None
        for _ in range(40):
            d = d + timedelta(days=1)
            while not is_trading("us", d):
                d += timedelta(days=1)
            h, lo, c, o = session_bar(cur, sigma, rng)
            prices.append(c)
            cur = c
            zone = lo + (h - lo) / 3
            if o < zone:
                exit_bar = (d, h, lo, c, o, zone)
                break
        ex_d, h, lo, c, o, zone = exit_bar
        sgn = 1 if side == "LONG" else -1
        entry_p, exit_p, latest = price2(entry), price2(o), price2(c)
        peak = max(prices[:-1] + [entry_p]) if side == "LONG" else min(prices[:-1] + [entry_p])
        council = ("flow_capital_council_v1_5_20260727" if grade < date(2026, 8, 17) else
                   str(rng.choice(["flow_capital_council_v2_0_risk_gatekeeper_20260817",
                                   "flow_capital_council_v1_6_macro_v2_20260817"])))
        slot = str(rng.choice(["1340", "1340", "1340", "1630", "1930"]))
        zone_exit = price2(lo) + (price2(h) - price2(lo)) / 3
        rows.append({
            "ticker": W["tickers"][i], "side": side, "grade_date": grade.isoformat(), "entry_date": grade.isoformat(),
            "entry_price": entry_p, "grade_score": score, "stop_price": zone_exit, "take_profit_price": None,
            "ratchet_armed": False, "peak_price": price2(peak), "horizon_end_date": None, "drop_out_zone": zone_exit,
            "drop_out_zone_date": ex_d.isoformat(), "drop_out_zone_day_high": price2(h),
            "drop_out_zone_day_low": price2(lo), "drop_out_observed_price": exit_p,
            "drop_out_observed_at": f"{ex_d.isoformat()}T19:56:{int(rng.integers(20, 50)):02d}+00:00",
            "status": "closed", "latest_price": latest, "latest_price_date": ex_d.isoformat(),
            "unrealized_return_pct": round(sgn * (latest / entry_p - 1) * 100, 4), "exit_date": ex_d.isoformat(),
            "exit_price": exit_p, "close_reason": "drop_out_zone",
            "realized_return_pct": round(sgn * (exit_p / entry_p - 1) * 100, 4),
            "holding_days": (ex_d - grade).days,
            "gates": gates_block(side, grade, price2(l0) + (price2(h0) - price2(l0)) / 3, price2(o0),
                                 f"flow_capital_live_v22_{grade:%Y%m%d}T{slot}", council),
        })
    rows.sort(key=lambda r: r["grade_date"], reverse=True)
    # today's opener decisions: strict grades exist, but the council review is a month old -> rejected
    today = date(2026, 10, 6)
    decisions = []
    for k, (n, side, score) in enumerate(((rated[0], "LONG", 86.0), (rated[4], "LONG", 76.0), (rated[9], "SHORT", 11.0))):
        i = W["index"][n["ticker"]]
        p = float(F["price"][i])
        zdate = prev_trading("us", today, [0, 3, 27][k])
        zone = round(p * (1 + [0.006, -0.004, -0.05][k]), 4)
        observed = round(zone * (1 - 0.005) if k == 0 else zone * 1.003, 4)
        decisions.append({
            "ticker": n["ticker"], "side": side, "grade_date": today.isoformat(),
            "grade_score": score + float(rng.uniform(0, 0.99)), "qualifies": False,
            "reject_reasons": ["six-area promoted review incomplete (4/6)",
                               f"council review stale (review_date={CKPT_SESSION}, gate requires >= "
                               f"{prev_trading('us', today).isoformat()})",
                               "same-session Drop Out Zone unavailable or observed price is below it"],
            "built_at": iso(utc(2026, 10, 7, 0, 40, 27, 178600 + 50 * k)),
            "gates": {**gates_block(side, today, zone, observed, CKPT_ID,
                                    "flow_capital_council_v3_0_risk_weight_only_20260904", fresh=False, reviewed=4,
                                    rating_schema="flow_capital_council_rating_v2_0",
                                    review_date=date.fromisoformat(CKPT_SESSION)),
                      "drop_out_zone_date": zdate.isoformat()},
        })
    data = {
        "market": "us", "rows": rows, "decisions": decisions,
        "exit_contract": {"rule": "drop_out_zone_only", "formula": ZONE_FORMULA,
                          "trigger": "observed_price < same_session_drop_out_zone", "entry_cutoff_can_exit": False,
                          "fixed_stop_enabled": False, "take_profit_enabled": False, "profit_ratchet_enabled": False,
                          "time_exit_enabled": False},
        "disclaimer": "Single paper book: a grade above 70 opens LONG, below 30 opens SHORT, and 30 to 70 opens "
                      "nothing. Positions close only through the Drop Out Zone rule. Research documentation, not "
                      "investment advice.",
    }
    return {"ok": True, "schema_version": "surgeflow.ai_grade_book.v1", "source": "/api/fund/grade-positions",
            "market": "us", "note": NOTE, "data": data}


# ---------------------------------------------------------------------------- macro calendar
# Live (market=us, days=14) lists only upcoming releases: actual and surprise are null, status is
# "scheduled" (consensus known) or "missing_consensus". cn/jp/hk files are the same shape for ?market=<m>.
MARKET_TZ = {"us": "America/New_York", "cn": "Asia/Shanghai", "jp": "Asia/Tokyo", "hk": "Asia/Hong_Kong"}
# (indicator, category, importance, unit, local date or weekday 0-4 for weekly, local time, previous, sd, decimals)
MACRO_EVENTS = {
    "us": [
        ("MBA Mortgage Applications", "housing", "low", "%", 2, "07:00", -1.2, 3.0, 1),
        ("MBA 30-Year Mortgage Rate", "housing", "low", "%", 2, "07:00", 6.4, 0.05, 2),
        ("EIA Crude Oil Stocks Change", "other", "medium", "M", 2, "10:30", -1.8, 2.5, 3),
        ("EIA Gasoline Stocks Change", "other", "low", "M", 2, "10:30", 0.9, 1.5, 3),
        ("API Crude Oil Stock Change", "other", "low", "M", 1, "16:30", 2.1, 2.5, 3),
        ("Initial Jobless Claims", "labor", "high", "K", 3, "08:30", 228, 9, 0),
        ("Continuing Jobless Claims", "labor", "medium", "K", 3, "08:30", 1934, 20, 0),
        ("4-Week Bill Auction", "other", "low", "%", 3, "11:30", 4.02, 0.03, 3),
        ("8-Week Bill Auction", "other", "low", "%", 3, "11:30", 4.01, 0.03, 3),
        ("6-Month Bill Auction", "other", "low", "%", 0, "11:30", 3.9, 0.03, 3),
        ("3-Month Bill Auction", "other", "low", "%", 0, "11:30", 3.96, 0.03, 3),
        ("Baker Hughes Oil Rig Count", "other", "low", None, 4, "13:00", 418, 4, 0),
        ("Fed Balance Sheet", "other", "low", "T", 3, "16:30", 6.61, 0.01, 2),
        ("Redbook YoY", "other", "low", "%", 1, "08:55", 5.4, 0.5, 1),
        ("FOMC Minutes", "other", "high", None, "2026-10-08", "14:00", None, None, 1),
        ("Consumer Credit Change (Aug)", "credit", "low", "B", "2026-10-07", "15:00", 16.0, 4.0, 2),
        ("Wholesale Inventories MoM (Aug)", "trade", "low", "%", "2026-10-08", "10:00", 0.1, 0.2, 1),
        ("Michigan Consumer Sentiment Prel (Oct)", "survey", "high", None, "2026-10-09", "10:00", 55.1, 1.2, 1),
        ("Michigan Inflation Expectations Prel (Oct)", "inflation", "medium", "%", "2026-10-09", "10:00", 4.7, 0.2, 1),
        ("Monthly Budget Statement (Sep)", "other", "medium", "B", "2026-10-09", "14:00", -345.0, 30.0, 0),
        ("NFIB Business Optimism Index (Sep)", "survey", "low", "Points", "2026-10-13", "06:00", 100.8, 1.0, 1),
        ("Inflation Rate YoY (Sep)", "inflation", "high", "%", "2026-10-14", "08:30", 2.9, 0.1, 1),
        ("Inflation Rate MoM (Sep)", "inflation", "high", "%", "2026-10-14", "08:30", 0.4, 0.1, 1),
        ("Core Inflation Rate YoY (Sep)", "inflation", "high", "%", "2026-10-14", "08:30", 3.1, 0.1, 1),
        ("Core Inflation Rate MoM (Sep)", "inflation", "high", "%", "2026-10-14", "08:30", 0.3, 0.1, 1),
        ("CPI s.a (Sep)", "inflation", "low", "Points", "2026-10-14", "08:30", 323.4, 0.6, 1),
        ("Real Earnings MoM (Sep)", "inflation", "low", "%", "2026-10-14", "08:30", -0.1, 0.2, 1),
        ("NY Empire State Manufacturing Index (Oct)", "survey", "medium", "Points", "2026-10-15", "08:30", -8.7, 5.0, 1),
        ("PPI MoM (Sep)", "inflation", "medium", "%", "2026-10-15", "08:30", -0.1, 0.2, 1),
        ("PPI YoY (Sep)", "inflation", "medium", "%", "2026-10-15", "08:30", 2.6, 0.2, 1),
        ("Retail Sales MoM (Sep)", "growth", "high", "%", "2026-10-15", "08:30", 0.6, 0.3, 1),
        ("Retail Sales Ex Autos MoM (Sep)", "growth", "medium", "%", "2026-10-15", "08:30", 0.7, 0.3, 1),
        ("Business Inventories MoM (Aug)", "trade", "low", "%", "2026-10-15", "10:00", 0.2, 0.2, 1),
        ("NAHB Housing Market Index (Oct)", "housing", "medium", "Points", "2026-10-15", "10:00", 32, 2, 0),
        ("Philadelphia Fed Manufacturing Index (Oct)", "survey", "medium", "Points", "2026-10-16", "08:30", 23.2, 6.0, 1),
        ("Industrial Production MoM (Sep)", "growth", "medium", "%", "2026-10-16", "09:15", 0.1, 0.2, 1),
        ("Capacity Utilization (Sep)", "growth", "low", "%", "2026-10-16", "09:15", 77.4, 0.2, 1),
        ("Housing Starts (Sep)", "housing", "medium", "M", "2026-10-19", "08:30", 1.307, 0.05, 3),
        ("Building Permits Prel (Sep)", "housing", "medium", "M", "2026-10-19", "08:30", 1.312, 0.05, 3),
        ("Export Prices MoM (Sep)", "trade", "low", "%", "2026-10-20", "08:30", 0.3, 0.2, 1),
        ("Import Prices MoM (Sep)", "trade", "low", "%", "2026-10-20", "08:30", 0.3, 0.2, 1),
        ("Existing Home Sales (Sep)", "housing", "medium", "M", "2026-10-21", "10:00", 4.0, 0.08, 2),
        ("13-Week Bill Auction", "other", "low", "%", 0, "11:30", 3.93, 0.03, 3),
        ("26-Week Bill Auction", "other", "low", "%", 0, "11:30", 3.86, 0.03, 3),
        ("52-Week Bill Auction", "other", "low", "%", 1, "11:30", 3.72, 0.03, 3),
        ("17-Week Bill Auction", "other", "low", "%", 2, "11:30", 3.9, 0.03, 3),
        ("EIA Natural Gas Stocks Change", "other", "low", None, 3, "10:30", 61.0, 15.0, 0),
        ("EIA Distillate Stocks Change", "other", "low", "M", 2, "10:30", -1.1, 1.5, 3),
        ("Fed Speech", "other", "medium", None, 1, "13:00", None, None, 1),
        ("Fed Speech", "other", "low", None, 3, "15:30", None, None, 1),
        ("Atlanta Fed GDPNow (Q3)", "growth", "medium", "%", 4, "10:30", 3.8, 0.3, 1),
        ("3-Year Note Auction", "other", "low", "%", "2026-10-07", "13:00", 3.62, 0.03, 3),
        ("10-Year Note Auction", "other", "medium", "%", "2026-10-08", "13:00", 4.11, 0.03, 3),
        ("30-Year Bond Auction", "other", "medium", "%", "2026-10-09", "13:00", 4.69, 0.03, 3),
        ("Fed Beige Book", "other", "medium", None, "2026-10-15", "14:00", None, None, 1),
        ("Total Vehicle Sales (Sep)", "growth", "low", "M", "2026-10-13", "TBD", 16.1, 0.3, 1),
        ("Net Long-term TIC Flows (Aug)", "other", "low", "B", "2026-10-16", "16:00", 150.8, 40.0, 1),
    ],
    "cn": [
        ("Foreign Exchange Reserves (Sep)", "other", "medium", "B", "2026-10-09", "16:00", 3322.0, 12.0, 1),
        ("Caixin Services PMI (Sep)", "survey", "medium", "Points", "2026-10-09", "09:45", 53.0, 0.6, 1),
        ("Caixin Composite PMI (Sep)", "survey", "low", "Points", "2026-10-09", "09:45", 51.9, 0.6, 1),
        ("New Yuan Loans (Sep)", "credit", "medium", "B", "2026-10-13", "15:00", 590.0, 180.0, 0),
        ("M2 Money Supply YoY (Sep)", "credit", "medium", "%", "2026-10-13", "15:00", 8.8, 0.2, 1),
        ("Total Social Financing (Sep)", "credit", "low", "B", "2026-10-13", "15:00", 2570.0, 300.0, 0),
        ("Balance of Trade (Sep)", "trade", "high", "B", "2026-10-14", "11:00", 102.3, 9.0, 1),
        ("Exports YoY (Sep)", "trade", "high", "%", "2026-10-14", "11:00", 4.4, 1.8, 1),
        ("Imports YoY (Sep)", "trade", "medium", "%", "2026-10-14", "11:00", 1.3, 1.5, 1),
        ("Inflation Rate YoY (Sep)", "inflation", "high", "%", "2026-10-15", "09:30", 0.8, 0.2, 1),
        ("Inflation Rate MoM (Sep)", "inflation", "medium", "%", "2026-10-15", "09:30", 0.1, 0.2, 1),
        ("PPI YoY (Sep)", "inflation", "medium", "%", "2026-10-15", "09:30", -2.9, 0.2, 1),
        ("House Price Index YoY (Sep)", "housing", "low", "%", "2026-10-19", "09:30", -4.1, 0.3, 1),
        ("GDP Growth Rate YoY (Q3)", "growth", "high", "%", "2026-10-19", "10:00", 5.2, 0.15, 1),
        ("GDP Growth Rate QoQ (Q3)", "growth", "medium", "%", "2026-10-19", "10:00", 1.1, 0.15, 1),
        ("Industrial Production YoY (Sep)", "growth", "high", "%", "2026-10-19", "10:00", 5.2, 0.4, 1),
        ("Retail Sales YoY (Sep)", "growth", "high", "%", "2026-10-19", "10:00", 3.4, 0.5, 1),
        ("Fixed Asset Investment YTD (Sep)", "growth", "medium", "%", "2026-10-19", "10:00", 0.5, 0.4, 1),
        ("Unemployment Rate (Sep)", "labor", "medium", "%", "2026-10-19", "10:00", 5.3, 0.1, 1),
        ("Loan Prime Rate 1Y", "credit", "high", "%", "2026-10-20", "09:00", 3.0, None, 2),
        ("Loan Prime Rate 5Y", "credit", "medium", "%", "2026-10-20", "09:00", 3.5, None, 2),
        ("Swift Global Payments CNY (Sep)", "other", "low", "%", "2026-10-16", "TBD", 3.0, 0.2, 2),
    ],
    "jp": [
        ("Household Spending YoY (Aug)", "other", "medium", "%", "2026-10-09", "08:30", -3.6, 1.2, 1),
        ("Average Cash Earnings YoY (Aug)", "labor", "medium", "%", "2026-10-08", "08:30", 3.4, 0.4, 1),
        ("Current Account (Aug)", "trade", "medium", "B", "2026-10-08", "08:50", 2989.0, 350.0, 1),
        ("Bank Lending YoY (Sep)", "credit", "low", "%", "2026-10-08", "08:50", 4.0, 0.2, 1),
        ("Eco Watchers Survey Current (Sep)", "survey", "low", "Points", "2026-10-08", "14:00", 46.7, 1.0, 1),
        ("Foreign Bond Investment", "other", "low", "B", 3, "08:50", -480.0, 600.0, 1),
        ("Stock Investment by Foreigners", "other", "low", "B", 3, "08:50", 1210.0, 700.0, 1),
        ("PPI YoY (Sep)", "inflation", "medium", "%", "2026-10-14", "08:50", 2.7, 0.2, 1),
        ("PPI MoM (Sep)", "inflation", "low", "%", "2026-10-14", "08:50", -0.2, 0.2, 1),
        ("Machinery Orders MoM (Aug)", "growth", "medium", "%", "2026-10-15", "08:50", -4.6, 2.5, 1),
        ("Industrial Production MoM Final (Aug)", "growth", "low", "%", "2026-10-15", "13:30", -1.6, 0.3, 1),
        ("Tertiary Industry Index MoM (Aug)", "growth", "low", "%", "2026-10-15", "13:30", 0.5, 0.3, 1),
        ("Balance of Trade (Sep)", "trade", "medium", "B", "2026-10-16", "08:50", -242.5, 90.0, 1),
        ("Exports YoY (Sep)", "trade", "medium", "%", "2026-10-16", "08:50", -0.1, 2.0, 1),
        ("Inflation Rate YoY (Sep)", "inflation", "high", "%", "2026-10-16", "08:30", 2.7, 0.1, 1),
        ("Core Inflation Rate YoY (Sep)", "inflation", "high", "%", "2026-10-16", "08:30", 2.7, 0.1, 1),
        ("Reuters Tankan Index (Oct)", "survey", "low", "Points", "2026-10-14", "08:00", 13, 3, 0),
        ("Jibun Bank Manufacturing PMI Flash (Oct)", "survey", "medium", "Points", "2026-10-21", "09:30", 48.5, 0.4, 1),
    ],
    "hk": [
        ("Foreign Exchange Reserves (Sep)", "other", "low", "B", "2026-10-08", "16:30", 442.9, 2.0, 1),
        ("S&P Global PMI (Sep)", "survey", "medium", "Points", "2026-10-07", "08:30", 50.7, 0.6, 1),
        ("Business Confidence (Q4)", "survey", "low", "%", "2026-10-16", "16:30", -4, 3, 0),
        ("Unemployment Rate (Sep)", "labor", "medium", "%", "2026-10-20", "16:30", 3.8, 0.1, 1),
        ("Inflation Rate YoY (Sep)", "inflation", "medium", "%", "2026-10-21", "16:30", 1.1, 0.2, 1),
        ("HKMA Base Rate", "credit", "medium", "%", "2026-10-16", "TBD", 4.5, None, 2),
        ("Industrial Production YoY (Q2)", "growth", "low", "%", "2026-10-14", "16:30", 2.1, 0.5, 1),
        ("Balance of Trade (Sep)", "trade", "medium", "B", "2026-10-20", "16:30", -35.4, 6.0, 1),
        ("Exports YoY (Sep)", "trade", "medium", "%", "2026-10-20", "16:30", 14.3, 3.0, 1),
        ("Imports YoY (Sep)", "trade", "low", "%", "2026-10-20", "16:30", 15.9, 3.0, 1),
        ("M3 Money Supply YoY (Aug)", "credit", "low", "%", "2026-10-09", "16:30", 8.1, 0.6, 1),
        ("Government Budget Value (Sep)", "other", "low", "B", "2026-10-15", "16:30", -12.0, 8.0, 1),
    ],
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def macro_payload(m: str, days: int = 14) -> dict:
    rng = rng_for("macro", m)
    cfg = CFG[m]
    tz = timezone(timedelta(hours=cfg["offset"]))
    end = NOW + timedelta(days=days)
    events = []
    for name, cat, imp, unit, when, t, prev, sd, nd in MACRO_EVENTS[m]:
        if isinstance(when, int):  # weekly release on that weekday; the name carries the reference week
            dates = [d for d in (TODAY + timedelta(days=k) for k in range(days + 1)) if d.weekday() == when]
        else:
            dates = [date.fromisoformat(when)]
        for d in dates:
            tbd = t == "TBD"  # live: a TBD release sits at 00:00 UTC and local_time carries the local date only
            if tbd:
                rel = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
                local = rel.astimezone(tz)
            else:
                hh, mm = map(int, t.split(":"))
                local = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
                rel = local.astimezone(timezone.utc)
            if not NOW <= rel <= end:
                continue
            label = name
            if isinstance(when, int) and prev is not None and "Auction" not in name:  # weekly data: reference week
                ref = d - timedelta(days=5 if when >= 2 else 7)
                label = f"{name} ({MONTHS[ref.month - 1]}/{ref.day:02d})"
            p = prev
            if p is not None and sd is not None:
                p = round(prev + float(rng.normal(0, sd * 0.5)), nd)
            if p is not None and rng.random() < 0.12:
                p = None
            has_cons = p is not None and sd is not None and rng.random() < 0.35
            cons = round(p + float(rng.normal(0, sd * 0.4)), nd) if has_cons else None
            if nd == 0:
                p = float(int(p)) if p is not None else None
                cons = float(int(cons)) if cons is not None else None
            events.append({
                "event_id": md5id(m, label, d), "market": m, "country": cfg["short"], "indicator_name": label,
                "category": cat, "release_time_utc": iso(rel), "local_time": local.strftime("%Y-%m-%d %H:%M") if not tbd
                else local.date().isoformat(), "market_tz": MARKET_TZ[m], "importance": imp, "previous": p, "consensus": cons,
                "actual": None, "surprise": None, "unit": unit, "status": "scheduled" if cons is not None else
                "missing_consensus", "source": "fmp", "time_tbd": tbd, "is_upcoming": True,
            })
    events.sort(key=lambda e: (e["release_time_utc"], e["indicator_name"]))
    data = {"days": days, "source": "fmp", "available": True, "last_checked_utc": "2026-10-07T05:00:14.528104+00:00",
            "stale": False, "market": m, "events": events}
    return {"ok": True, "schema_version": "surgeflow.macro_calendar.v1", "source": "/api/macro/calendar", "market": m,
            "data": {"ok": True, "data": data}}


# ---------------------------------------------------------------------------- bond ETFs
BOND_ETFS = [
    # ticker, name, short label, category, fund category, base AUM, expense %, price, maturity yrs, sec yield %, inception
    ("LQD", "iShares iBoxx $ Investment Grade Corporate Bond ETF", "iBoxx $ IG Corp", "US Investment Grade", "Corporate Bond", 2.6e10, 0.14, 104.0, 13.0, 4.8, "2002-07-22"),
    ("USIG", "iShares Broad USD Investment Grade Corporate Bond ETF", "Broad USD IG Corp", "US Investment Grade", "Corporate Bond", 1.6e10, 0.04, 50.6, 10.6, 4.9, "2007-01-05"),
    ("IGSB", "iShares 1-5 Year Investment Grade Corporate Bond ETF", "1-5 Year IG Corp", "US Investment Grade", "Short-Term Bond", 2.2e10, 0.04, 52.2, 3.8, 4.4, "2007-01-05"),
    ("IGIB", "iShares 5-10 Year Investment Grade Corporate Bond ETF", "5-10 Year IG Corp", "US Investment Grade", "Corporate Bond", 1.7e10, 0.04, 52.9, 8.4, 4.9, "2007-01-05"),
    ("IGLB", "iShares 10+ Year Investment Grade Corporate Bond ETF", "10+ Year IG Corp", "US Investment Grade", "Long-Term Bond", 2.4e9, 0.04, 49.6, 22.2, 5.5, "2009-12-08"),
    ("HYG", "iShares iBoxx $ High Yield Corporate Bond ETF", "iBoxx $ HY Corp", "US High Yield", "High Yield Bond", 1.6e10, 0.49, 80.3, 5.6, 6.3, "2007-04-04"),
    ("USHY", "iShares Broad USD High Yield Corporate Bond ETF", "Broad USD HY Corp", "US High Yield", "High Yield Bond", 2.4e10, 0.08, 37.2, 5.5, 6.8, "2017-10-25"),
    ("SHYG", "iShares 0-5 Year High Yield Corporate Bond ETF", "0-5 Year HY Corp", "US High Yield", "High Yield Bond", 7.0e9, 0.30, 43.1, 3.2, 6.9, "2013-10-15"),
    ("FALN", "iShares Fallen Angels USD Bond ETF", "Fallen Angels USD", "US High Yield", "High Yield Bond", 1.5e9, 0.25, 27.4, 9.6, 6.5, "2016-06-14"),
    ("AGG", "iShares Core U.S. Aggregate Bond ETF", "US Aggregate Bond", "US Broad Market", "Intermediate Core Bond", 1.3e11, 0.03, 99.4, 11.9, 4.4, "2003-09-22"),
]


def bond_payload() -> dict:
    rng = rng_for("bond")
    rows = []
    for (tk, name, short, cat, fcat, aum, er, px, mat, sec, inc) in BOND_ETFS:
        close = round(px * float(np.exp(rng.normal(0, 0.01))), 2)
        sec_y = round(sec + float(rng.normal(0, 0.08)), 2)
        treas = round(4.85 + 0.035 * mat + float(rng.normal(0, 0.05)), 4)
        rows.append({
            "ticker": tk, "name": name, "asset_class": "Fixed Income", "etf_company": "iShares",
            "aum": money(aum * float(np.exp(rng.normal(0, 0.05)))), "aum_source": "yahoo_quote_summary",
            "expense_ratio": er, "expense_ratio_source": "yahoo_quote_summary",
            "nav": round(close * (1 - float(rng.uniform(0.001, 0.006))), 5), "nav_source": "yahoo_quote_summary",
            "last_close": close, "pct_change_1d": round(float(rng.normal(0.32, 0.08)), 3),
            "volume": money(aum / px * float(rng.uniform(0.005, 0.03))), "avg_volume": None,
            "return_1y_pct": round(-0.45 * mat + float(rng.normal(-1.0, 0.8)), 3),
            "return_ytd_pct": round(-0.38 * mat + float(rng.normal(-1.2, 0.6)), 3), "latest_bar_date": "2026-10-06",
            "inception_date": inc, "inception_date_source": "yahoo_quote_summary", "metadata_completeness": "complete",
            "metadata_methodology_version": "bond_etf_metadata_fallback_v2_20260730", "category": cat,
            "market_region": "us", "short_label": short, "sec_yield_30d_pct": sec_y,
            "ytm_proxy_pct": round(sec_y - float(rng.uniform(0.05, 0.6)), 4), "avg_maturity_years": round(mat, 3),
            "matched_treasury_yield_pct": treas, "credit_spread_bps": round((sec_y - treas) * 100, 1),
            "fund_category": fcat, "treasury_curve_date": "2026-10-02",
        })
    return {"ok": True, "schema_version": "surgeflow.bond_etfs.v1", "source": "/api/bond/etfs",
            "data": {"ok": True, "data": {"etfs": rows}}}


# ---------------------------------------------------------------------------- daily notes
# Live notes are member content: the structure below follows the live response, every sentence is a neutral
# placeholder generated from the fixture's own numbers.
NOTES_DATE = "2026-10-07"
NOTES_GENERATED = utc(2026, 10, 7, 1, 20, 37, 448120)
MARKET_TITLE = {"us": "US", "cn": "China", "jp": "Japan", "hk": "Hong Kong"}
LENS_SOURCE = {"macro": "stock_sentiment_score_v1", "sentiment": "stock_sentiment_score_v1",
               "factor": "stock_scores_latest_v1", "technical": "stock_scores_latest_v1",
               "fundamental": "stock_scores_latest_v1", "risk": "ticker_risk_metrics_latest_v1"}
SENTIMENT_INPUTS = ["news", "management outlook", "management reputation", "industry rotation"]


def agent_rating(W: dict, i: int, rng) -> dict:
    """notes_agent_rating_v1: six 1-5 lenses; top_down = mean(macro, sentiment, factor), bottom_up = mean(technical,
    fundamental, risk), overall = mean(top_down, bottom_up)."""
    mom, vol, qual, val, grow, attn = W["lat"][i][:6]
    as_of = W["cfg"]["eod"]

    def five(x):
        return int(np.clip(round(3 + 1.1 * x + rng.normal(0, 0.5)), 1, 5))

    values = {"macro": None if rng.random() < 0.08 else five(rng.normal(0, 1)),
              "sentiment": five(0.5 * attn + 0.3 * mom), "factor": five(0.4 * mom + 0.3 * val + 0.3 * qual),
              "technical": five(0.8 * mom), "fundamental": None if rng.random() < 0.03 else five(0.6 * qual + 0.4 * grow),
              "risk": five(-0.8 * vol)}
    lenses = {}
    for lens, v in values.items():
        expl, state = None, "available"
        if lens == "sentiment" and rng.random() < 0.95:
            k = int(rng.integers(1, 4))
            missing = [str(x) for x in rng.choice(SENTIMENT_INPUTS, size=4 - k, replace=False)]
            expl, state = f"Uses {k} of 4 inputs; missing: {', '.join(missing)}.", "partial"
        if lens == "factor":
            expl = "Derived from the available within-market momentum, value and quality percentiles."
        lenses[lens] = {"value": v, "state": state, "as_of": as_of if lens != "risk" else
                        prev_trading(W["m"], date.fromisoformat(as_of), int(rng.integers(0, 2))).isoformat(),
                        "source": LENS_SOURCE[lens], "explanation": expl}

    def mean(keys):
        vals = [values[k] for k in keys if values[k] is not None]
        return round(float(np.mean(vals)), 2) if vals else None

    top, bottom = mean(["macro", "sentiment", "factor"]), mean(["technical", "fundamental", "risk"])
    n_ok = sum(v is not None for v in values.values())
    return {"schema_version": "notes_agent_rating_v1", "as_of": as_of, "state": "available" if n_ok == 6 else "partial",
            "available_lenses": n_ok, "total_lenses": 6, "overall": round((top + bottom) / 2, 2), "top_down": top,
            "bottom_up": bottom, "lenses": lenses}


def note_row_base(W: dict, i: int) -> dict:
    return {"ticker": W["tickers"][i], "name": W["names"][i], "sector": W["sectors"][i], "industry": W["industries"][i]}


def notes_market(W: dict) -> dict:
    m, cfg, F, N = W["m"], W["cfg"], W["F"], W["N"]
    rng = rng_for("notes", m)
    eod = cfg["eod"]
    title = MARKET_TITLE[m]
    cap_ok = F["market_cap_usd"] >= 4e8

    def urls(i, tab_url):
        return {"ticker_url": f"{SITE}/stock/{m}/{W['tickers'][i]}", "tab_url": tab_url}

    sections = []
    # 1. price momentum
    has_ind = np.array([x is not None for x in W["industries"]])
    cap_ok = cap_ok & has_ind
    cand = np.where(cap_ok & (W["S"]["rsi_state"] != "overbought") & (F["avwap_cushion"] >= 0))[0]
    top = sorted(cand, key=lambda i: -F["trend_run"][i])[:5]
    rows = []
    for k, i in enumerate(top):
        r = note_row_base(W, i)
        r.update({"market_cap": int(round(F["market_cap"][i])), "market_cap_usd": int(round(F["market_cap_usd"][i])),
                  "price": float(F["price"][i]), "avwap": num(F["avwap"][i]), "avwap_cushion": num(F["avwap_cushion"][i], 6),
                  "trend_run": num(F["trend_run"][i]), "rsi_14": num(F["rsi_14"][i]), "rsi_state": str(W["S"]["rsi_state"][i]),
                  "change_pct": num(F["change_pct"][i], 6), "return_5d": num(F["ret_5d"][i], 6),
                  "ytd_return": num(F["ytd_return"][i], 6), **urls(i, f"{SITE}/price")})
        if k == 0:
            r["trend_making_streak_days"] = int(rng.integers(4, 50))
        r["agent_rating"] = agent_rating(W, i, rng)
        rows.append(r)
    sections.append({"tab": "ma_breakthrough", "label": "Price Momentum", "ok": True, "as_of_date": eod,
                     "source_url": f"{SITE}/api/{m}/screen?sort=trend_run&dir=desc&tab=ma_breakthrough&limit=300",
                     "tab_url": f"{SITE}/price",
                     "headline": f"Price Momentum (placeholder): {len(cand)} fixture names pass the filter; top trend_run "
                                 f"{F['trend_run'][top[0]]:.2f}." if top else "Price Momentum (placeholder): no names pass.",
                     "filter": "market_cap_usd >= 400M AND rsi_state != overbought AND price >= avwap",
                     "sort": "trend_run desc", "top_rows": rows, "error": None})
    # 2. turnover surge (CN: the board is on its holiday session, nothing qualifies - as live)
    turnover_usd = F["turnover"] / cfg["fx"]
    cand = [] if m == "cn" else np.where(cap_ok & (turnover_usd >= 2.5e7) & (F["to_yest_mult"] >= 1.0))[0]
    top = sorted(cand, key=lambda i: -F["to_yest_mult"][i])[:5]
    rows = []
    for i in top:
        r = note_row_base(W, i)
        r.update({"turnover": money(F["turnover"][i]), "turnover_usd": money(turnover_usd[i]),
                  "market_cap": int(round(F["market_cap"][i])), "market_cap_usd": int(round(F["market_cap_usd"][i])),
                  "turnover_ratio": num(F["turnover_ratio"][i], 6), "to_yest_mult": num(F["to_yest_mult"][i]),
                  "change_pct": num(F["change_pct"][i], 6), "return_5d": num(F["ret_5d"][i], 6),
                  "ytd_return": num(F["ytd_return"][i], 6), **urls(i, f"{SITE}/turnover"),
                  "agent_rating": agent_rating(W, i, rng)})
        rows.append(r)
    sections.append({"tab": "turnover", "label": "Turnover Surge", "ok": True, "as_of_date": eod,
                     "source_url": f"{SITE}/api/{m}/screen?sort=to_yest_mult&dir=desc&tab=turnover&limit=300",
                     "tab_url": f"{SITE}/turnover",
                     "headline": f"Turnover Surge (placeholder): {len(cand)} fixture names trade at least their prior-day "
                                 "turnover." if len(cand) else "Turnover Surge (placeholder): no qualifying names this session.",
                     "filter": "market_cap_usd >= 400M AND turnover_usd >= 25M AND to_yest_mult >= 1.0",
                     "sort": "to_yest_mult desc", "top_rows": rows, "error": None})
    # 3. market structure: leading sector trend and industry inflow
    secs = [s for s in SECTORS if s in W["sectors"]]
    ret63 = {s: float(np.average(F["ret_63d"][[i for i in range(N) if W["sectors"][i] == s]],
                                 weights=F["market_cap"][[i for i in range(N) if W["sectors"][i] == s]])) for s in secs}
    lead_sec = max(secs, key=lambda s: ret63[s])
    inds = [x for x in dict.fromkeys(W["industries"]) if x]
    tw = {x: float(F["turnover"][[i for i in range(N) if W["industries"][i] == x]].sum() / F["turnover"].sum()) for x in inds}
    cw = {x: float(F["market_cap"][[i for i in range(N) if W["industries"][i] == x]].sum() / F["market_cap"].sum()) for x in inds}
    lead_ind = max(inds, key=lambda x: tw[x] - cw[x])
    sections.append({
        "tab": "market_structure", "label": "Market Structure", "ok": True, "as_of_date": eod,
        "source_url": "example_project.stock_data.v_sector_rolling_60d_v1 + example_project.stock_data.industry_rotation_latest_v1",
        "tab_url": f"{SITE}/turnover",
        "headline": f"Market Structure (placeholder): {lead_sec} leads the fixture sector trend; {lead_ind} shows the "
                    "largest turnover-versus-cap inflow.",
        "methodology": "Sector Trend = change in the 60-day moving average of sector excess returns; Industry Inflow = "
                       "turnover weight minus market-cap weight.",
        "top_rows": [
            {"structure_type": "Sector Trend", "leader": lead_sec, "metric_label": "Trend",
             "metric_value": float(abs(rng.normal(0.002, 0.004))), "secondary_label": "60D Return",
             "secondary_value": ret63[lead_sec], "member_count": W["sectors"].count(lead_sec), "as_of_date": eod,
             "source": "Excess Returns", "tab_url": f"{SITE}/price"},
            {"structure_type": "Industry Inflow", "leader": lead_ind, "metric_label": "Surprise",
             "metric_value": round(tw[lead_ind] - cw[lead_ind], 6), "secondary_label": "Turnover Ratio",
             "secondary_value": round(tw[lead_ind] / cw[lead_ind], 4), "turnover_weight_pct": round(100 * tw[lead_ind], 4),
             "market_cap_weight_pct": round(100 * cw[lead_ind], 4), "member_count": W["industries"].count(lead_ind),
             "as_of_date": prev_trading(m, date.fromisoformat(eod), 10).isoformat(), "source": "Industry Rotation",
             "tab_url": f"{SITE}/turnover"},
        ],
        "error": None})
    # 4. whales: the top five of each board
    boards = W["WH"]["boards"]
    sections.append({
        "tab": "whales", "label": "Whales", "ok": True, "as_of_date": "2026-10-07",
        "source_url": f"{SITE}/api/whales/signal-board?market={m}&limit=5", "tab_url": f"{SITE}/whales",
        "headline": f"Whales (placeholder): consensus leader {boards['consensus'][0]['ticker']} in the fixture boards.",
        "lines": [f"Placeholder: {b} leader is {boards[b][0]['ticker']}." for b in ("conviction", "position_delta", "network")],
        "leaders": {b: [dict(r) for r in rows_[:5]] for b, rows_ in boards.items()}})
    # 5. fundamental valuation
    cq = F["composite_quality"]
    strict = cap_ok & (F["ytd_return"] >= 0) & (np.nan_to_num(F["change_pct"]) >= 0) & (np.nan_to_num(F["revenue_growth"]) > 0) \
        & (np.nan_to_num(F["profit_margin"]) > 0)
    cand = np.where(cap_ok & np.isfinite(cq))[0]
    top = sorted(cand, key=lambda i: (-int(strict[i]), -cq[i]))[:5]
    rows = []
    for i in top:
        r = note_row_base(W, i)
        r.update({"market_cap": int(round(F["market_cap"][i])), "market_cap_usd": int(round(F["market_cap_usd"][i])),
                  "revenue_growth": num(F["revenue_growth"][i]), "profit_margin": num(F["profit_margin"][i]),
                  "composite_quality": num(cq[i], 6), "change_pct": num(F["change_pct"][i], 6),
                  "return_5d": num(F["ret_5d"][i], 6), "ytd_return": num(F["ytd_return"][i], 6), "ep": num(F["ep"][i]),
                  "cfop": num(F["cfop"][i]), **urls(i, f"{SITE}/fundamentals"), "agent_rating": agent_rating(W, i, rng)})
        rows.append(r)
    sections.append({"tab": "fundamental", "label": "Fundamental Valuation", "ok": True, "as_of_date": eod,
                     "source_url": f"{SITE}/api/{m}/screen?tab=fundamental&limit=300", "tab_url": f"{SITE}/fundamentals",
                     "headline": f"Fundamental Valuation (placeholder): {int(strict.sum())} fixture names pass the strict "
                                 "filter.",
                     "filter": "market_cap_usd >= 400M; strict first: ytd_return >= 0 AND change_pct >= 0 AND "
                               "revenue_growth > 0 AND profit_margin > 0; fill to 5 by composite_quality",
                     "sort": "strict_pass desc, composite_quality desc", "top_rows": rows, "error": None})
    # 6. macro risk
    lead, coin, lag = W["MACRO_CYCLE"]
    sections.append({"tab": "macro", "label": "Macro Risk", "ok": True, "as_of_date": "2026-09-30",
                     "source_url": "example_project.stock_data.macro_cycle_composites_v2",
                     "headline": f"Macro Risk (placeholder): leading {lead:+.2f}, coincident {coin:+.2f}, lagging {lag:+.2f}.",
                     "lines": ["Placeholder line: composite scores are synthetic fixture values."] * (1 if m == "hk" else 3),
                     "scores": {"leading": lead, "coincident": coin, "lagging": lag}})
    # 7. ML market map (and 8. AI analyst team, US only)
    ml_names = W["ml_names"]
    biggest = ml_names[max(ml_names, key=lambda g: int(np.sum(W["ML"]["labels"][W["ML"]["eligible"]] == g)))]
    sections.append({"tab": "ml_clusters", "label": "ML Market Map", "ok": True,
                     "headline": f"ML Market Map (placeholder): {len(ml_names)} clusters; largest is '{biggest}'.",
                     "lines": [f"Placeholder line {k}: see the ml/clusters fixture for the numbers." for k in (1, 2, 3)],
                     "tab_url": f"{SITE}/ml?market={m}", "as_of_date": cfg["ml"]["as_of"]})
    if m == "us":
        sections.append({"tab": "ai_agents", "label": "AI Analyst Team", "ok": True,
                         "headline": "AI Analyst Team (placeholder): see the ai/ratings fixture for the checkpoint.",
                         "lines": [f"Placeholder line {k}: synthetic council summary." for k in range(1, 6)],
                         "tab_url": f"{SITE}/ai", "as_of_date": "2026-10-06"})
    # 9. news & sentiment (three fixture articles)
    arts = W["NEWS"][:3]
    sections.append({"tab": "news", "label": "News & Sentiment", "ok": True,
                     "source_url": f"{SITE}/api/news/feed?market={m}&limit=3", "tab_url": f"{SITE}/news",
                     "headline": f"News & Sentiment (placeholder): {len(W['NEWS'])} fixture articles, mean score "
                                 f"{np.mean([a['sentiment_score'] for a in W['NEWS']]):+.2f}.",
                     "lines": ["Placeholder line: headlines are synthetic.", "Placeholder line: scores are synthetic."],
                     "articles": [dict(a) for a in arts], "error": None})
    return note_record(title, "market", m, f"Daily conclusion for {title}, ready to copy.", sections,
                       {"market": m, "section_count": len(sections), "ok_sections": len(sections)})


def note_record(title: str, scope: str, market: str, subtitle: str, sections: list, status: dict) -> dict:
    full_title = f"{'SurgeFlow' if scope == 'global' else title} Daily Notes — {NOTES_DATE}"
    body = [f"# {full_title}", "", f"Source dashboard: {SITE}/notes", ""]
    for s in sections:
        body += [f"## {s['label']}", s["headline"]] + [f"- {x}" for x in s.get("lines", [])] + [""]
    markdown = "\n".join(body).rstrip() + "\n"
    watch = "SurgeFlow cross-market watch" if scope == "global" else f"{title} market watch"
    x_post = "\n".join([f"{watch} - {NOTES_DATE}", "Placeholder post generated from fixture data."]
                       + [s["headline"][:90] for s in sections[:3]] + [f"{SITE}/notes"])
    return {"as_of_date": NOTES_DATE, "generated_at": iso(NOTES_GENERATED), "scope": scope, "market": market,
            "title": full_title, "subtitle": subtitle, "website_url": f"{SITE}/notes", "x_post": x_post,
            "reddit_post": markdown, "copy_markdown": markdown, "methodology_version": "daily_notes_v1_0",
            "updated_at": iso(NOTES_GENERATED), "sections": sections, "source_status": status}


def notes_global(worlds: dict, bond: dict) -> dict:
    etf = bond["data"]["data"]["etfs"][0]
    sections = [
        {"tab": "macro-fx", "label": "Macro / FX", "ok": True,
         "headline": f"Macro / FX (placeholder): fixture USD/JPY {CFG['jp']['fx']}, USD/CNY {CFG['cn']['fx']}.",
         "source_url": f"{SITE}/api/macro/fx-triangular"},
        {"tab": "bond", "label": "Bond", "ok": True,
         "headline": f"Bond (placeholder): {etf['ticker']} latest bar {etf['latest_bar_date']}; 1D "
                     f"{etf['pct_change_1d']:+.2f}% in the fixture.",
         "source_url": f"{SITE}/api/bond/etfs"},
        {"tab": "macro-event", "label": "Event", "ok": True,
         "headline": "Event (placeholder): prediction-market summary omitted from the fixture.",
         "source_url": f"{SITE}/api/macro/polymarket?region=us&category=elections&min_volume_24h=10000"},
        {"tab": "news", "label": "News", "ok": True,
         "headline": "News (placeholder): composite fear/greed reading omitted from the fixture.",
         "source_url": f"{SITE}/api/news/composite-fear-greed?region=west"},
        {"tab": "markets", "label": "Markets", "ok": True,
         "headline": "Markets (placeholder): one line per market from the fixture screens.",
         "lines": [f"{MARKET_TITLE[m]}: placeholder line; median daily change "
                   f"{100 * float(np.nanmedian(worlds[m]['F']['change_pct'])):+.2f}% in the fixture." for m in MARKETS]},
    ]
    return note_record("SurgeFlow", "global", "all", "Cross-market conclusion across the SurgeFlow tabs, ready to copy.",
                       sections, {"market_count": 4, "section_count": len(sections) - 1, "ok_sections": len(sections) - 1})


def notes_payload(notes: list[dict], market: str) -> dict:
    data = {
        "ok": True, "count": len(notes), "as_of_date": NOTES_DATE, "market": market, "notes": notes,
        "methodology_version": "daily_notes_v1_0",
        "agent_rating_contract": {
            "schema_version": "notes_agent_rating_v1", "status": "available", "scale": {"min": 1, "max": 5},
            "top_down": ["macro", "sentiment", "factor"], "bottom_up": ["technical", "fundamental", "risk"],
            "method": "Deterministic within-market evidence lenses, materialised daily. Research diagnostics, not votes."},
        "disclosure": "Research context only. Notes summarise SurgeFlow dashboard data and are not investment advice. "
                      "Fixture notes are synthetic placeholders.",
    }
    return {"ok": True, "schema_version": "surgeflow.daily_notes.v1", "source": "/api/notes/daily", "market": market,
            "data": data}


# ---------------------------------------------------------------------------- me
def me_payload() -> dict:
    """GET /api/v1/me. All identifiers are fake; notebooks must never print key_prefix, member_id,
    referral_code, invite_url or referrals."""
    code = "sfri_" + "x" * 20
    return {
        "ok": True, "schema_version": "surgeflow.public_api.v1", "key_prefix": "sf_live_xxxx",
        "member_id": "m_" + "0" * 24, "plan": "free",
        "scopes": ["ai", "factors", "hotlist", "macro", "ml", "news", "notes", "realtime", "screen", "summary", "whales"],
        "key_created_at": "2026-10-01T09:12:44.120518+00:00", "founding_analyst_number": 99, "is_founding_analyst": True,
        "referral_code": code,
        "invite_url": f"{SITE}/membership?utm_source=member_invite&utm_medium=referral&utm_campaign=member_referral"
                      f"&utm_content=quest&utm_id={code}#api-key",
        "referrals": {"registered": 0, "first_value_reached": 0, "repeat_value_reached": 0},
        "rate_limit": {"X-RateLimit-Limit": "180", "X-RateLimit-Remaining": "179", "X-RateLimit-Daily-Limit": "2000",
                       "X-RateLimit-Daily-Remaining": "1912", "X-SurgeFlow-RateLimit-Store": "gcs"},
        "usage": {"used_7d": 88, "used_30d": 241, "last_used_at": "2026-10-07T05:14:09.551203+00:00",
                  "first_value_reached": True, "value_days_30d": 6, "repeat_value_reached": True,
                  "note": "Rolling request counts and distinct research days from the daily usage ledger; updated in "
                          "batches, so the last few minutes may be missing."},
    }


# ---------------------------------------------------------------------------- build all
def build() -> dict[str, dict]:
    files: dict[str, dict] = {}
    worlds = {}
    for m in MARKETS:
        W = build_world(m)
        rng = rng_for("macro_cycle", m)
        W["MACRO_CYCLE"] = (round(float(rng.uniform(-1.7, 0.3)), 4), round(float(rng.uniform(-0.3, 0.8)), 4),
                            round(float(rng.uniform(0.1, 0.75)), 4))
        W["ML"] = ml_state(W)
        W["WH"] = whales_state(W)
        W["NEWS"] = news_articles(W)
        worlds[m] = W
    gate_total = sum(len(gate_rows(m)) for m in MARKETS)
    bond = bond_payload()
    for m in MARKETS:
        W = worlds[m]
        files.update(screen_payloads(W))
        files[f"sector_{m}.json"] = sector_payload(W)
        files[f"realtime_{m}.json"] = realtime_payload(W)
        files[f"hotlist_{m}.json"] = hotlist_payload(W)
        files[f"ml_clusters_{m}.json"] = ml_payload(W)
        files[f"whales_{m}.json"] = whales_payload(W, gate_total)
        files[f"news_{m}.json"] = news_payload(W)
        files[f"factor_portfolios_{m}.json"] = fp_payload(W)
    files["summary.json"] = summary_payload(worlds)
    ratings, rated = ai_ratings_payload(worlds["us"])
    files["ai_ratings.json"] = ratings
    files["ai_grade_book.json"] = grade_book_payload(worlds["us"], rated)
    macro = {m: macro_payload(m) for m in MARKETS}
    files["macro_calendar.json"] = macro["us"]  # default market=us
    for m in ("cn", "jp", "hk"):
        files[f"macro_calendar_{m}.json"] = macro[m]  # tools/mock_api.py serves these for ?market=<m>
    files["bond_etfs.json"] = bond
    notes = {m: notes_market(worlds[m]) for m in MARKETS}
    order = [notes_global(worlds, bond)] + [notes[m] for m in sorted(MARKETS)]  # live order: global, cn, hk, jp, us
    files["notes_daily.json"] = notes_payload(order, "all")  # default market=all
    for m in MARKETS:
        files[f"notes_daily_{m}.json"] = notes_payload([notes[m]], m)  # ?market=<m> (inferred: that market's note)
    files["me.json"] = me_payload()
    assert not set(files) & set(REAL_FIXTURES)
    return files


def render(payload: dict) -> str:
    return json.dumps(clean(payload), indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare with the files on disk; write nothing")
    args = parser.parse_args()
    files = {name: render(payload) for name, payload in build().items()}
    if args.check:
        stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != text]
        for n in stale:
            print(f"stale: {n}")
        print("fixtures up to date" if not stale else f"{len(stale)} stale fixture(s)")
        return 1 if stale else 0
    total = 0
    for name, text in sorted(files.items()):
        (OUT / name).write_text(text)
        total += len(text.encode())
    print(f"wrote {len(files)} fixtures, {total / 1e6:.2f} MB (catalog.json and health.json untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
