const ADDIN_DATA_POLICY = {
  "momentum-hotlist": {
    enabled: true,
    // Store products show only SurgeFlow tickers, ranks, and stock links from live board rows.
    mode: "ticker_rank",
    markets: {
      us: { enabled: true, drop_columns: [] },
      cn: { enabled: true, drop_columns: [] },
      jp: { enabled: true, drop_columns: [] },
      hk: { enabled: true, drop_columns: [] }
    }
  },
  "factor-overview": {
    enabled: false,
    markets: {
      us: { enabled: false, drop_columns: [] },
      cn: { enabled: false, drop_columns: [] },
      jp: { enabled: false, drop_columns: [] },
      hk: { enabled: false, drop_columns: [] }
    }
  },
  "macro-indicators": {
    enabled: true,
    markets: {
      all: {
        enabled: true,
        drop_columns: ["freshness_detail", "age_hours"],
        // Exact match on the source text before the first ":"; any other prefix is never written.
        allow_source_prefixes: ["ons", "boe", "estat", "censtatd", "cbc", "dgbas", "us-treasury", "U.S. Treasury", "worldbank"],
        credits: {
          "ons": "Source: Office for National Statistics. Contains public sector information licensed under the Open Government Licence v3.0.",
          "boe": "Source: Bank of England statistical database. Open Government Licence v3.0.",
          "estat": "Source: e-Stat, Portal Site of Official Statistics of Japan.",
          "censtatd": "Source: Census and Statistics Department, HKSAR Government, via DATA.GOV.HK.",
          "cbc": "Source: Central Bank of the Republic of China (Taiwan); DGBAS. Open Government Data License, Taiwan, v1.0.",
          "dgbas": "Source: Central Bank of the Republic of China (Taiwan); DGBAS. Open Government Data License, Taiwan, v1.0.",
          "us-treasury": "Source: U.S. Department of the Treasury, Fiscal Data.",
          "U.S. Treasury": "Source: U.S. Department of the Treasury, Fiscal Data.",
          "worldbank": "Source: World Bank, World Development Indicators. CC BY 4.0."
        }
      }
    }
  },
  "data-freshness": {
    enabled: true,
    markets: {
      all: { enabled: true, drop_columns: [] }
    }
  }
};
