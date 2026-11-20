/** @OnlyCurrentDoc */

const SURGEFLOW_SNAPSHOT_BASE = 'https://surgeflows.capital/api/public/snapshots/';
const SURGEFLOW_ERROR_MESSAGE = 'SurgeFlow data could not be loaded. Try again later.';
const SURGEFLOW_DISCLAIMER = 'Research data only; not investment advice. Market data may be delayed.';
const SURGEFLOW_DATASETS = {
  'momentum-hotlist': { market: true, sheet: 'SurgeFlow Hotlist' },
  'factor-overview': { market: true, sheet: 'SurgeFlow Factors' },
  'macro-indicators': { market: false, sheet: 'SurgeFlow Macro Indicators' },
  'data-freshness': { market: false, sheet: 'SurgeFlow Data Freshness' }
};
const SURGEFLOW_MARKETS = ['us', 'cn', 'jp', 'hk'];
const SURGEFLOW_HOTLIST_LINK_HEADERS = ['market', 'market_phase', 'display_status', 'as_of', 'count', 'total_count', 'link'];
const SURGEFLOW_HOTLIST_TICKER_RANK_HEADERS = ['market', 'ticker', 'selection_rank', 'link'];
const SURGEFLOW_FRESHNESS_EXTRA_HEADERS = ['overall_status', 'max_stale_trading_days', 'timezone'];

function addinAvailableMarkets(datasetId) {
  const definition = SURGEFLOW_DATASETS[datasetId];
  const policy = ADDIN_DATA_POLICY[datasetId];
  if (!definition || !policy || policy.enabled === false) return [];
  const marketIds = definition.market ? SURGEFLOW_MARKETS : ['all'];
  return marketIds.filter(function (marketId) {
    const marketPolicy = policy.markets && policy.markets[marketId];
    return marketPolicy && marketPolicy.enabled !== false;
  });
}

function addinPickerDatasets() {
  return Object.keys(SURGEFLOW_DATASETS).map(function (datasetId) {
    return {
      id: datasetId,
      takesMarket: SURGEFLOW_DATASETS[datasetId].market,
      markets: addinAvailableMarkets(datasetId)
    };
  }).filter(function (dataset) {
    return dataset.markets.length > 0;
  });
}

function getAddinPickerConfig() {
  return addinPickerDatasets();
}

function onOpen(e) {
  SpreadsheetApp.getUi()
    .createMenu('SurgeFlow')
    .addItem('Insert data…', 'showSidebar')
    .addItem('About', 'showAbout')
    .addToUi();
}

function onInstall(e) {
  onOpen(e);
}

function showSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar').setTitle('SurgeFlow');
  SpreadsheetApp.getUi().showSidebar(html);
}

function showAbout() {
  SpreadsheetApp.getUi().alert(
    'SurgeFlow',
    'Read no-key public research snapshots without signing in.\n\n' +
      SURGEFLOW_DISCLAIMER +
      '\n\nhttps://surgeflows.capital/\nhttps://surgeflows.capital/privacy\nhttps://surgeflows.capital/contact',
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function insertSnapshot(datasetId, market) {
  const definition = SURGEFLOW_DATASETS[datasetId];
  const normalizedMarket = String(market || 'us').toLowerCase();
  if (!definition || (definition.market && SURGEFLOW_MARKETS.indexOf(normalizedMarket) === -1)) {
    throw new Error(SURGEFLOW_ERROR_MESSAGE);
  }
  const policyMarket = definition.market ? normalizedMarket : 'all';
  if (addinAvailableMarkets(datasetId).indexOf(policyMarket) === -1) {
    throw new Error(SURGEFLOW_ERROR_MESSAGE);
  }
  const table = loadSnapshotTable(datasetId, definition.market ? normalizedMarket : '', policyMarket);
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const baseName = definition.sheet + (definition.market ? ' ' + normalizedMarket.toUpperCase() : '');
  let sheetName = baseName;
  let suffix = 2;
  while (spreadsheet.getSheetByName(sheetName)) {
    sheetName = baseName + ' (' + suffix + ')';
    suffix += 1;
  }

  const width = table.headers.length;
  const intro = [
    tableRow(['Source: ' + table.url + ' · fetched ' + table.fetchedAt], width),
    tableRow([SURGEFLOW_DISCLAIMER], width)
  ].concat(table.statusLines.map(function (line) {
    return tableRow([line], width);
  }));
  const body = [table.headers].concat(table.rows);
  const footer = table.footer.map(function (line) {
    return tableRow([line], width);
  });
  const sheet = spreadsheet.insertSheet(sheetName);
  // Plain text keeps leading-zero tickers and stops '=' strings from becoming formulas.
  sheet.getRange(1, 1, intro.length + body.length + footer.length, width).setNumberFormat('@');
  // autoResizeColumns reads whole columns, so size them on the header and data before the long source, disclaimer and footer lines exist.
  sheet.getRange(intro.length + 1, 1, body.length, width).setValues(body);
  sheet.getRange(intro.length + 1, 1, 1, width).setFontWeight('bold').setBackground('#f3f4f6');
  sheet.setFrozenRows(intro.length + 1);
  sheet.autoResizeColumns(1, width);
  sheet.getRange(1, 1, intro.length, width).setValues(intro);
  if (footer.length) sheet.getRange(intro.length + body.length + 1, 1, footer.length, width).setValues(footer);
  const linkColumn = table.headers.indexOf('link');
  if (linkColumn !== -1 && table.rows.length) {
    sheet.getRange(intro.length + 2, linkColumn + 1, table.rows.length, 1).setRichTextValues(table.rows.map(function (row) {
      const url = String(row[linkColumn]);
      return [SpreadsheetApp.newRichTextValue().setText(url).setLinkUrl(url).build()];
    }));
  }
  return { sheetName: sheetName, rowCount: table.rows.length, sourceUrl: table.url, fetchedAt: table.fetchedAt };
}

function tableRow(cells, width) {
  const row = cells.slice();
  while (row.length < width) row.push('');
  return row;
}

function loadSnapshotTable(datasetId, market, policyMarket) {
  const datasetPolicy = ADDIN_DATA_POLICY[datasetId];
  const policy = datasetPolicy.markets[policyMarket];
  const linkOnly = datasetPolicy.mode === 'link_only';
  const tickerRank = datasetPolicy.mode === 'ticker_rank';
  // Fail closed: the generic path writes every live column, so the Hotlist needs an allowed mode.
  if (datasetId === 'momentum-hotlist' && !linkOnly && !tickerRank) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  const suffix = market ? '?market=' + encodeURIComponent(market) : '';
  const jsonUrl = SURGEFLOW_SNAPSHOT_BASE + datasetId + '.json' + suffix;
  const csvUrl = SURGEFLOW_SNAPSHOT_BASE + datasetId + '.csv' + suffix;
  let payload;
  let headers;
  try {
    payload = JSON.parse(fetchSnapshotText(jsonUrl, 'application/json'));
    headers = linkOnly ? SURGEFLOW_HOTLIST_LINK_HEADERS.slice() : tickerRank ? SURGEFLOW_HOTLIST_TICKER_RANK_HEADERS.slice() : parseCsvHeader(fetchSnapshotText(csvUrl, 'text/csv'));
  } catch (error) {
    throw new Error(SURGEFLOW_ERROR_MESSAGE);
  }

  const droppedColumns = Array.isArray(policy.drop_columns) ? policy.drop_columns : [];
  headers = headers.filter(function (header) {
    return droppedColumns.indexOf(header) === -1;
  });
  if (datasetId === 'data-freshness') headers = headers.concat(SURGEFLOW_FRESHNESS_EXTRA_HEADERS);
  let sourceRows = linkOnly ? hotlistLinkRows(payload, market) : tickerRank ? hotlistTickerRankRows(payload, market) : snapshotRows(datasetId, payload);
  const statusLines = tickerRank ? hotlistStatusLines(payload, market, sourceRows.length) : [];
  const footer = [];
  if (Array.isArray(policy.allow_source_prefixes)) {
    sourceRows = sourceRows.filter(function (row) {
      return policy.allow_source_prefixes.indexOf(sourcePrefix(row)) !== -1;
    });
    sourceRows.forEach(function (row) {
      const credit = policy.credits && policy.credits[sourcePrefix(row)];
      if (credit && footer.indexOf(credit) === -1) footer.push(credit);
    });
  }
  if (datasetId === 'data-freshness') footer.push('Status computed by SurgeFlow.');
  if (linkOnly) footer.push('Open SurgeFlow for the current names.');
  if (tickerRank) footer.push("Open SurgeFlow for the full board. Ranks are SurgeFlow's own.");
  const rows = sourceRows.map(function (row) {
    return headers.map(function (header) {
      return scalarCell(row[header]);
    });
  });
  // An empty ticker_rank board is honest only when SurgeFlow says the board holds zero names.
  const emptyBoard = tickerRank && payload.data.total_count === 0;
  if (!headers.length || (!rows.length && !emptyBoard)) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return {
    url: jsonUrl,
    headers: headers,
    rows: rows,
    footer: footer,
    statusLines: statusLines,
    fetchedAt: Utilities.formatDate(new Date(), 'Etc/UTC', "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'")
  };
}

function sourcePrefix(row) {
  return String(row && row.source).split(':')[0];
}

function hotlistLinkRows(payload, market) {
  const data = payload && payload.data;
  if (!data || SURGEFLOW_MARKETS.indexOf(market) === -1) return [];
  return [{
    market: market,
    market_phase: data.market_phase,
    display_status: data.display_status,
    as_of: data.as_of,
    count: data.count,
    total_count: data.total_count,
    link: 'https://surgeflows.capital/momentum/' + market
  }];
}

function hotlistTickerRankRows(payload, market) {
  const data = payload && payload.data;
  if (!data || SURGEFLOW_MARKETS.indexOf(market) === -1 || !Array.isArray(data.rows)) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return data.rows.map(function (row) {
    if (!row || typeof row.ticker !== 'string' || !row.ticker ||
        typeof row.selection_rank !== 'number' || !isFinite(row.selection_rank) ||
        typeof row.stock_link !== 'string' || row.stock_link.indexOf('/stock/') !== 0) {
      throw new Error(SURGEFLOW_ERROR_MESSAGE);
    }
    return {
      market: market,
      ticker: row.ticker,
      selection_rank: row.selection_rank,
      link: 'https://surgeflows.capital' + row.stock_link
    };
  });
}

function hotlistStatusLines(payload, market, rowCount) {
  const data = payload.data;
  const lines = [
    'Market: ' + market,
    'Market phase: ' + scalarCell(data.market_phase),
    'Display status: ' + scalarCell(data.display_status),
    'As of: ' + scalarCell(data.as_of),
    'Board size: ' + scalarCell(data.total_count),
    'Truncated: ' + scalarCell(data.truncated)
  ];
  if (data.truncated) lines.push('Showing the top ' + rowCount + ' of ' + data.total_count + ' on the board');
  if (data.total_count === 0) lines.push('No names on the board right now');
  return lines;
}

function fetchSnapshotText(url, accept) {
  const response = UrlFetchApp.fetch(url, {
    method: 'get',
    muteHttpExceptions: true,
    headers: { Accept: accept }
  });
  if (response.getResponseCode() !== 200) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return response.getContentText();
}

function snapshotRows(datasetId, payload) {
  const data = payload && payload.data;
  if (!data) return [];
  if (datasetId === 'data-freshness') {
    return (Array.isArray(data.rows) ? data.rows : []).map(function (row) {
      return Object.assign({}, row, {
        overall_status: data.status,
        max_stale_trading_days: data.max_stale_trading_days,
        timezone: data.timezone
      });
    });
  }
  if (datasetId === 'factor-overview') {
    return (Array.isArray(data.publication_gates) ? data.publication_gates : []).map(function (row) {
      return Object.assign({}, row, {
        section: 'publication_gates',
        market: data.market
      });
    });
  }
  return Array.isArray(data.rows) ? data.rows : [];
}

function scalarCell(value) {
  if (value === undefined || value === null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return value;
}

function parseCsvHeader(text) {
  const headers = [];
  let field = '';
  let quoted = false;
  let terminated = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === ',' && !quoted) {
      headers.push(field);
      field = '';
    } else if ((character === '\n' || character === '\r') && !quoted) {
      if (field.length || headers.length) headers.push(field);
      terminated = true;
      break;
    } else {
      field += character;
    }
  }
  if (quoted) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  if (!terminated && (field.length || headers.length)) headers.push(field);
  if (!headers.length || headers.some(function (header) { return !header; })) {
    throw new Error(SURGEFLOW_ERROR_MESSAGE);
  }
  return headers;
}
