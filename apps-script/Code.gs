const SURGEFLOW_API_BASE = 'https://stock-api-c4qdowjxva-uc.a.run.app';
const MARKETS = ['us', 'cn', 'jp', 'hk', 'uk', 'in'];

const HOTLIST_COLS = [
  'hotlist_rank', 'market', 'ticker', 'company_name', 'industry', 'price',
  'intraday_return_pct', 'turnover_per_second', 'market_cap_usd',
  'projected_turnover_usd', 'projected_vs_yesterday', 'previous_day_turnover_usd'
];
const REALTIME_COLS = [
  'rank', 'ticker', 'company_name', 'price', 'intraday_return_pct',
  'turnover_per_second', 'accumulated_turnover', 'projected_turnover',
  'projected_vs_yesterday', 'previous_day_turnover'
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Surgeflow')
    .addItem('Open', 'showSidebar')
    .addSeparator()
    .addItem('Refresh US', 'refreshUS')
    .addItem('Refresh CN', 'refreshCN')
    .addItem('Refresh JP', 'refreshJP')
    .addItem('Refresh HK', 'refreshHK')
    .addItem('Refresh UK', 'refreshUK')
    .addItem('Refresh IN', 'refreshIN')
    .addToUi();
}

function onInstall(e) {
  onOpen(e);
}

function buildHomepage() {
  var card = CardService.newCardBuilder();
  card.setHeader(CardService.newCardHeader()
    .setTitle('Surgeflow')
    .setSubtitle('Market hotlist and realtime turnover'));

  var section = CardService.newCardSection();

  MARKETS.forEach(function(market) {
    section.addWidget(CardService.newTextButton()
      .setText('Refresh ' + market.toUpperCase())
      .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
      .setOnClickAction(CardService.newAction()
        .setFunctionName('refreshFromCard')
        .setParameters({ market: market })));
  });

  return card.addSection(section).build();
}

function showSidebar() {
  var html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setTitle('Surgeflow');
  SpreadsheetApp.getUi().showSidebar(html);
}

function refreshUS() { return refreshMarket('us'); }
function refreshCN() { return refreshMarket('cn'); }
function refreshJP() { return refreshMarket('jp'); }
function refreshHK() { return refreshMarket('hk'); }
function refreshUK() { return refreshMarket('uk'); }
function refreshIN() { return refreshMarket('in'); }

function refreshFromCard(e) {
  var market = e && e.parameters && e.parameters.market ? e.parameters.market : 'us';
  refreshMarket(market);
  return CardService.newActionResponseBuilder()
    .setNotification(CardService.newNotification().setText('Surgeflow ' + market.toUpperCase() + ' refreshed.'))
    .build();
}

function refreshMarket(market) {
  market = String(market || 'us').toLowerCase();
  if (MARKETS.indexOf(market) === -1) {
    throw new Error('Unsupported market: ' + market);
  }

  var realtime = fetchJson('/api/addin/realtime?market=' + encodeURIComponent(market) + '&limit=1000');
  var hotlist = fetchJson('/api/addin/hotlist?market=' + encodeURIComponent(market));

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var name = 'Surgeflow_' + market.toUpperCase();
  var sheet = ss.getSheetByName(name) || ss.insertSheet(name);
  sheet.clearContents();

  var nextRow = 1;
  nextRow = writeSection(sheet, nextRow, 'HOTLIST', hotlist, HOTLIST_COLS);
  writeSection(sheet, nextRow, 'REALTIME TABLE', realtime, REALTIME_COLS);

  sheet.autoResizeColumns(1, Math.max(HOTLIST_COLS.length, REALTIME_COLS.length));
  sheet.setFrozenRows(0);
  return {
    market: market,
    realtime_rows: realtime.count || 0,
    hotlist_rows: hotlist.count || 0,
    realtime_status: realtime.market_status || '',
    hotlist_status: hotlist.market_status || '',
    realtime_quality: realtime.data_quality || '',
    hotlist_quality: hotlist.data_quality || ''
  };
}

function fetchJson(path) {
  var response = UrlFetchApp.fetch(SURGEFLOW_API_BASE + path, {
    method: 'get',
    muteHttpExceptions: true,
    headers: { Accept: 'application/json' }
  });
  var status = response.getResponseCode();
  if (status < 200 || status >= 300) {
    throw new Error(path + ' -> HTTP ' + status + ': ' + response.getContentText().slice(0, 300));
  }
  return JSON.parse(response.getContentText());
}

function metaRows(payload, label) {
  return [
    ['section', label],
    ['market_status', scalar(payload.market_status)],
    ['market_quality', scalar(payload.data_quality)]
  ];
}

function rowValues(rows, cols) {
  return (rows || []).map(function(row) {
    return cols.map(function(col) {
      return scalar(row[col]);
    });
  });
}

function scalar(value) {
  if (value === undefined || value === null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return value;
}

function writeSection(sheet, startRow, title, payload, cols) {
  var meta = metaRows(payload, title);
  sheet.getRange(startRow, 1, meta.length, 2).setValues(meta);
  sheet.getRange(startRow, 1, meta.length, 1).setFontWeight('bold');
  sheet.getRange(startRow, 1, 1, 2).setBackground('#f8fafc');

  var headerRow = startRow + meta.length + 1;
  sheet.getRange(headerRow, 1, 1, cols.length).setValues([cols]);
  sheet.getRange(headerRow, 1, 1, cols.length).setFontWeight('bold').setBackground('#f3f4f6');

  var values = rowValues(payload.rows, cols);
  if (values.length) {
    sheet.getRange(headerRow + 1, 1, values.length, cols.length).setValues(values);
  }
  return headerRow + Math.max(values.length, 1) + 3;
}
