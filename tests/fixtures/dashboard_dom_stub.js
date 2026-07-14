// Reusable Node harness for testing the dashboard's client-side JS without
// a real browser. Usage: node dashboard_dom_stub.js <path-to-extracted-script.js>
// Prints one line of JSON summarizing render state after a sequence of
// simulated filter interactions, so the calling test can assert on it
// rather than scraping console output.
const path = require('path');
const scriptPath = process.argv[2];
if (!scriptPath) {
  console.error('Usage: node dashboard_dom_stub.js <path-to-extracted-script.js>');
  process.exit(2);
}

const registry = new Map();

class FakeClassList {
  constructor() { this._set = new Set(); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  contains(c) { return this._set.has(c); }
}

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.style = new Proxy({}, { set() { return true; } });
    this.classList = new FakeClassList();
    this._attrs = {};
    this._html = '';
    this._text = '';
    this._value = '';
    this._listeners = {};
  }
  setAttribute(k, v) {
    this._attrs[k] = v;
    if (k === 'id') registry.set(v, this);
  }
  appendChild(c) { this.children.push(c); return c; }
  append(...cs) { cs.forEach(c => this.children.push(c)); }
  get firstChild() { return this.children.length ? this.children[0] : null; }
  removeChild(c) {
    const i = this.children.indexOf(c);
    if (i >= 0) this.children.splice(i, 1);
    return c;
  }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  fire(type, evt) { (this._listeners[type] || []).forEach(fn => fn(evt || {})); }
  set innerHTML(v) { this._html = v; }
  get innerHTML() { return this._html; }
  set textContent(v) { this._text = v; }
  get textContent() { return this._text; }
  set value(v) { this._value = v; }
  get value() { return this._value; }
}

global.document = {
  getElementById(id) {
    if (!registry.has(id)) registry.set(id, new FakeElement('div'));
    return registry.get(id);
  },
  createElement(tag) { return new FakeElement(tag); },
  createElementNS(_ns, tag) { return new FakeElement(tag); },
  createTextNode(text) { return { text }; },
};
global.window = {};

function flattenText(elOrTextNode) {
  if (elOrTextNode === null || elOrTextNode === undefined) return '';
  if (elOrTextNode.text !== undefined) return elOrTextNode.text;
  return (elOrTextNode.children || []).map(flattenText).join('');
}

function snapshot() {
  const deltaCard = registry.get('delta-card');
  const firstChild = deltaCard.children[0];
  const isGrid = !!(firstChild && firstChild._attrs.class === 'delta-grid');
  const groups = isGrid ? firstChild.children : [];
  return {
    deltaSub: registry.get('delta-sub')._text,
    deltaIsEmptyState: !!(firstChild && firstChild._attrs.class === 'delta-empty'),
    deltaGroupHeadings: groups.map(g => flattenText(g.children[0])),
    tileCount: registry.get('tile-row').children.length,
    vendorBarCount: registry.get('vendor-bars').children.length,
    staleRowCount: registry.get('stale-tbody').children.length,
    deptBarCount: registry.get('dept-bars').children.length,
  };
}

require(path.resolve(scriptPath));

const out = { initial: snapshot() };
// download-sub/commitments-count/expenditure-count get their text set by
// JS; the <a href> targets are static markup the JS never touches, so
// those are checked directly against the rendered HTML string in Python
// instead of through this stub.
out.downloadSub = registry.get('download-sub')._text;
out.commitmentsCount = registry.get('commitments-count')._text;
out.expenditureCount = registry.get('expenditure-count')._text;

const deptFilterEl = registry.get('dept-filter');
const weekFilterEl = registry.get('week-filter');
const resetBtn = registry.get('filter-reset');

// Earliest week: no prior snapshot to diff against.
weekFilterEl.value = '0';
weekFilterEl.fire('change');
out.earliestWeek = snapshot();

// Back to the latest week, filtered to whichever department sorts first.
const lastWeekIdx = weekFilterEl.children.length - 1;
weekFilterEl.value = String(lastWeekIdx);
weekFilterEl.fire('change');
const firstDept = deptFilterEl.children.length ? deptFilterEl.children[0]._attrs.value : null;
if (firstDept) {
  deptFilterEl.value = firstDept;
  deptFilterEl.fire('change');
}
out.deptFiltered = snapshot();
out.firstDept = firstDept;

resetBtn.fire('click');
out.afterReset = snapshot();

console.log(JSON.stringify(out));
