'use strict';
/*
 * protrader_mobile.html is a single-file, no-build front end: every script
 * lives inline in one <script> tag with module-level state (PAIR_MAP, TR,
 * TK, ...), so the P&L/margin functions can't be `import`ed directly. This
 * pulls the exact source of the order-ticket money maths (otPnl,
 * otMarginFor, otConv, otSpec, otMoney, otAccount, ...) out of the HTML by
 * locating the same unique anchor comments/declarations a human would use
 * to find that code, and runs it in a sandboxed VM context so tests below
 * exercise the real shipped implementation rather than a re-typed copy.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const HTML_PATH = path.join(__dirname, '..', 'protrader_mobile.html');

function sliceBetween(src, startMarker, endMarker) {
  const start = src.indexOf(startMarker);
  if (start === -1) throw new Error(`extract_order_math: start marker not found: ${startMarker}`);
  const end = src.indexOf(endMarker, start);
  if (end === -1) throw new Error(`extract_order_math: end marker not found: ${endMarker}`);
  return src.slice(start, end);
}

function loadOrderMath() {
  const src = fs.readFileSync(HTML_PATH, 'utf8');

  // Block 1: S, PAIRS, PAIR_MAP, pairPrices — plain data + one forEach, no DOM.
  const stateBlock = sliceBetween(src, 'const S = {', 'const pairPrices = {};') + 'const pairPrices = {};\n';

  // Block 2: CLASS_SPECS ... otAccount — the actual ticket money maths.
  // Stops right before the Broker adapter section, which needs setTimeout
  // and isn't part of the maths under test.
  const mathBlock = sliceBetween(src, 'const CLASS_SPECS = {', '/* ── Broker adapter');

  // NEXUS is defined later in the file (feed-freshness bookkeeping); otQuote
  // only reads NEXUS.staleMs, so shim just that field with the real value
  // (protrader_mobile.html:staleMs — keep in sync if that constant changes).
  const shim = 'const NEXUS = { staleMs: 12000 };\n';

  const exportLine = `
globalThis.__orderMath = {
  otSpec, otFmtPx, otMoney, otMoneyAuto, otQuote, otMarketOpen, otClosedNote,
  otMinDist, otConv, otPnl, otPipValue, otMarginFor, otAccount,
  PAIR_MAP, pairPrices, otBook, otInfo, otDigits, TR, TK, S,
  CLASS_SPECS, SPEC_OVERRIDE,
};
`;

  const code = shim + stateBlock + '\n' + mathBlock + '\n' + exportLine;
  const sandbox = { console };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: 'protrader_mobile.html (extracted order math)' });
  return sandbox.__orderMath;
}

module.exports = { loadOrderMath };
