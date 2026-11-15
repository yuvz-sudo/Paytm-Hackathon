// Whole-app translation into the merchant's language (Sarvam AI, via /api/i18n/translate).
//
// Rather than hand-wrapping every string, this watches the rendered page and translates English text in place:
// - React-safe: only the text value of existing nodes changes (no elements are added or removed), and when React
//   writes new English text the observer sees it and translates that.
// - Cheap: numbers are templated ("{1} payments"), translations are cached in localStorage and on the server, and
//   strings are sent in batches.
// - Opt-out: anything inside translate="no" / .notranslate (names, the brand, typed input) stays as it is.
// - Hand-written Hindi from i18n.tsx wins over machine translation.
import { api } from "./api";
import { HI } from "./i18n";
import { UI_IN_ENGLISH } from "./languages";

const LATIN = /[A-Za-z]{2,}/;
const INDIC = /[ऀ-෿]/;
const NUM = /Dukaan Saathi|Saathi|Paytm|₹?\d[\d,]*(?:\.\d+)?%?/g; // numbers and brand names are never translated
const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "SELECT", "OPTION", "CODE", "PRE", "NOSCRIPT"]);
const ATTRS = ["placeholder", "title", "aria-label"];
const BATCH = 60;
const VERSION = "v3"; // bump with the server glossary (CACHE_VERSION) to drop stale translations

type Rec = { src: string; out: string };
let lang = "en";
let root: HTMLElement | null = null;
let observer: MutationObserver | null = null;
const textRec = new Map<Text, Rec>();
const attrRec = new Map<Element, Record<string, Rec>>();
let dict: Record<string, string> = {};      // templated English -> templated translation, for `lang`
const pending = new Set<string>();           // exact strings waiting for the server
const retryAfter = new Map<string, number>(); // strings the server could not translate: do not hammer it
let timer: number | undefined;
let inflight = 0;
const attempts = new Map<string, number>();
let rescanTimer: number | undefined;
let rescanAt = Infinity;

function rescanIn(ms: number) {
  const at = Date.now() + ms + 50;
  if (rescanTimer !== undefined && rescanAt <= at) return; // an earlier rescan is already booked
  clearTimeout(rescanTimer);
  rescanAt = at;
  const forLang = lang;
  rescanTimer = window.setTimeout(() => { rescanTimer = undefined; rescanAt = Infinity; if (root && lang === forLang && observer) scan(root); }, ms + 50);
}

// Back off 3 s, 6 s, 12 s ... up to a minute, then look at the page again so the string is requested once more.
function later(s: string) {
  const n = (attempts.get(s) || 0) + 1;
  attempts.set(s, n);
  const delay = Math.min(60_000, 3000 * 2 ** (n - 1));
  retryAfter.set(s, Date.now() + delay);
  rescanIn(delay);
}
let saveTimer: number | undefined;

function template(s: string): [string, string[]] {
  const nums: string[] = [];
  const t = s.replace(NUM, (m) => { nums.push(m); return `{${nums.length}}`; });
  return [t, nums];
}
function fill(t: string, nums: string[]): string | null {
  let out = t;
  for (let i = 0; i < nums.length; i++) {
    const ph = `{${i + 1}}`;
    if (!out.includes(ph)) return null;
    out = out.split(ph).join(nums[i]);
  }
  return /\{\d+\}/.test(out) ? null : out;
}

const key = (l: string) => `i18n:${VERSION}:${l}`;
function loadDict(l: string): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(key(l)) || "{}") || {}; } catch { return {}; }
}
function saveDict() {
  clearTimeout(saveTimer);
  const l = lang, d = dict;
  saveTimer = window.setTimeout(() => {
    try {
      const keys = Object.keys(d);
      if (keys.length > 4000) for (const k of keys.slice(0, keys.length - 4000)) delete d[k];
      localStorage.setItem(key(l), JSON.stringify(d));
    } catch { /* storage full or blocked: the in-memory copy still works */ }
  }, 400);
}

function lookup(s: string): string | null {
  if (lang === "hi" && HI[s]) return HI[s];
  const [t, nums] = template(s);
  const tr = dict[t];
  return (tr ? fill(tr, nums) : null) ?? dict[s] ?? null;
}

function wanted(s: string) {
  return s.length <= 400 && LATIN.test(s) && !INDIC.test(s);
}

function skipped(el: Element | null): boolean {
  for (let e = el; e; e = e.parentElement) {
    if (SKIP_TAGS.has(e.tagName)) return true;
    if (e.getAttribute("translate") === "no" || e.classList.contains("notranslate")) return true;
    if ((e as HTMLElement).isContentEditable) return true;
    if (e === root) return false;
  }
  return false;
}

function ask(s: string) {
  const until = retryAfter.get(s);
  if (until && until > Date.now()) { if (attempts.has(s)) rescanIn(until - Date.now()); return; }
  pending.add(s);
  if (timer === undefined) timer = window.setTimeout(flush, 120);
}

function doText(node: Text) {
  const v = node.nodeValue || "";
  const rec = textRec.get(node);
  if (rec && v === rec.out) return;          // our own translation
  const s = v.trim();
  if (!s || !wanted(s) || skipped(node.parentElement)) { textRec.delete(node); return; }
  const tr = lookup(s);
  if (tr == null) { textRec.delete(node); ask(s); return; }
  const out = v.replace(s, () => tr);
  textRec.set(node, { src: v, out });
  node.nodeValue = out;
}

function doAttr(el: Element, a: string) {
  const v = el.getAttribute(a);
  if (v == null) return;
  const recs = attrRec.get(el) || {};
  const rec = recs[a];
  if (rec && v === rec.out) return;
  const s = v.trim();
  // an input's own placeholder/label is translated; what is typed inside it never is (that is not an attribute)
  const own = el.getAttribute("translate") === "no" || el.classList.contains("notranslate");
  if (!s || !wanted(s) || own || skipped(el.parentElement)) { delete recs[a]; return; }
  const tr = lookup(s);
  if (tr == null) { ask(s); return; }
  recs[a] = { src: v, out: tr };
  attrRec.set(el, recs);
  el.setAttribute(a, tr);
}

function scan(node: Node) {
  if (node.nodeType === Node.TEXT_NODE) { doText(node as Text); return; }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const el = node as Element;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) doText(n as Text);
  for (const a of ATTRS) {
    if (el.hasAttribute(a)) doAttr(el, a);
    el.querySelectorAll(`[${a}]`).forEach((x) => doAttr(x, a));
  }
}

function prune() {
  for (const n of textRec.keys()) if (!n.isConnected) textRec.delete(n);
  for (const e of attrRec.keys()) if (!e.isConnected) attrRec.delete(e);
}

async function flush() {
  timer = undefined;
  if (UI_IN_ENGLISH.has(lang) || !pending.size || inflight >= 2) {
    if (pending.size && !UI_IN_ENGLISH.has(lang)) timer = window.setTimeout(flush, 300);
    return;
  }
  const texts = Array.from(pending).slice(0, BATCH);
  texts.forEach((t) => pending.delete(t));
  const forLang = lang;
  inflight++;
  try {
    const r = await api<{ translations: string[]; retry?: number[] }>("/i18n/translate", { method: "POST", body: { language: forLang, texts } });
    if (forLang !== lang) return;
    const busy = new Set(r.retry || []);
    texts.forEach((src, i) => {
      const out = r.translations?.[i];
      if (busy.has(i)) { later(src); return; }     // Sarvam was busy: ask again soon
      if (!out || out === src) { retryAfter.set(src, Date.now() + 30 * 60_000); return; } // nothing to translate (a name)
      attempts.delete(src);
      // store as a template so the same label with a different number is instant next time
      const [tSrc, nums] = template(src);
      if (nums.length) {
        let tOut = out;
        nums.forEach((n, j) => { tOut = tOut.replace(n, `{${j + 1}}`); });
        if (fill(tOut, nums) === out) { dict[tSrc] = tOut; return; }
      }
      dict[src] = out; // exact match (numbers moved around in the translation)
    });
    saveDict();
  } catch {
    texts.forEach(later);
  } finally {
    inflight--;
  }
  if (forLang === lang && root) { prune(); scan(root); }
  if (pending.size && timer === undefined) timer = window.setTimeout(flush, 50);
}

function restore() {
  for (const [n, rec] of textRec) if (n.nodeValue === rec.out) n.nodeValue = rec.src;
  for (const [el, recs] of attrRec) for (const a in recs) if (el.getAttribute(a) === recs[a].out) el.setAttribute(a, recs[a].src);
  textRec.clear(); attrRec.clear(); pending.clear();
}

/** Switch the whole page to `next`. Call with the merchant's language whenever it changes. */
export function setUiLanguage(next: string, el: HTMLElement | null = document.getElementById("root")) {
  if (next === lang && el === root && (observer || UI_IN_ENGLISH.has(next))) return;
  observer?.disconnect();
  observer = null;
  restore();
  lang = next;
  root = el;
  dict = loadDict(next);
  retryAfter.clear();
  attempts.clear();
  document.documentElement.lang = next === "hinglish" ? "hi" : next === "od" ? "or" : next;
  if (UI_IN_ENGLISH.has(next) || !root) return;
  observer = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === "characterData") doText(m.target as Text);
      else if (m.type === "attributes" && m.attributeName) doAttr(m.target as Element, m.attributeName);
      else m.addedNodes.forEach(scan);
    }
  });
  observer.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  scan(root);
}

/** Translate an arbitrary English string right now (for text that is not on the page, e.g. what to speak). */
export function translated(s: string): string {
  if (UI_IN_ENGLISH.has(lang)) return s;
  return lookup(s.trim()) ?? s;
}
