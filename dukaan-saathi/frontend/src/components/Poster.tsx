import { useEffect, useRef } from "react";

type Theme = { a: string; b: string; accent: string; ink: string; motif: "diya" | "dots" | "stars" | "rays" };
const THEMES: [RegExp, Theme][] = [
  [/diwali|deepavali|दिवाली/i, { a: "#ff9a3c", b: "#b3125b", accent: "#ffe08a", ink: "#ffffff", motif: "diya" }],
  [/holi|होली/i, { a: "#ff4d8d", b: "#6a1bb1", accent: "#ffe14d", ink: "#ffffff", motif: "dots" }],
  [/eid|ramzan|ramadan|ईद/i, { a: "#0f9d7a", b: "#06433a", accent: "#ffe9a8", ink: "#ffffff", motif: "stars" }],
  [/navratri|dussehra|durga|नवरात्रि/i, { a: "#e53935", b: "#7a0c0c", accent: "#ffd54f", ink: "#ffffff", motif: "rays" }],
  [/christmas|new year|नया साल/i, { a: "#1e88e5", b: "#0b2a63", accent: "#ffffff", ink: "#ffffff", motif: "stars" }],
  [/weekend|sale|special|offer/i, { a: "#00b9f5", b: "#012b72", accent: "#ffe14d", ink: "#ffffff", motif: "rays" }],
];
const DEFAULT: Theme = { a: "#00b9f5", b: "#012b72", accent: "#ffe14d", ink: "#ffffff", motif: "rays" };
export const themeFor = (occasion: string): Theme => (THEMES.find(([rx]) => rx.test(occasion)) || [null, DEFAULT])[1] as Theme;

const OFF = { en: "OFF", hi: "छूट", hinglish: "OFF" } as Record<string, string>;
const VALID = { en: (d: number) => `Valid for ${d} days`, hi: (d: number) => `${d} दिन तक मान्य`, hinglish: (d: number) => `${d} din tak valid` } as Record<string, (d: number) => string>;
const SIZE = 1080;

function wrap(ctx: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const words = text.split(/\s+/); const lines: string[] = []; let cur = "";
  for (const w of words) { const t = cur ? `${cur} ${w}` : w; if (ctx.measureText(t).width > maxW && cur) { lines.push(cur); cur = w; } else cur = t; }
  if (cur) lines.push(cur);
  return lines.slice(0, 3);
}

function draw(c: HTMLCanvasElement, shop: string, occasion: string, pct: number, days: number, lang: string) {
  const ctx = c.getContext("2d"); if (!ctx) return;
  const t = themeFor(occasion); const font = '"Noto Sans Devanagari","Segoe UI",system-ui,sans-serif';
  c.width = c.height = SIZE;
  const g = ctx.createLinearGradient(0, 0, SIZE, SIZE); g.addColorStop(0, t.a); g.addColorStop(1, t.b);
  ctx.fillStyle = g; ctx.fillRect(0, 0, SIZE, SIZE);
  // decoration, deterministic so the same campaign always looks the same
  ctx.globalAlpha = 0.16; ctx.fillStyle = t.accent;
  let seed = [...occasion].reduce((s, ch) => s + ch.charCodeAt(0), 7); const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  if (t.motif === "rays") { ctx.translate(SIZE / 2, SIZE * 0.42); for (let i = 0; i < 16; i++) { ctx.rotate(Math.PI / 8); ctx.fillRect(0, -18, SIZE, 36); } ctx.setTransform(1, 0, 0, 1, 0, 0); }
  else for (let i = 0; i < 34; i++) {
    const x = rnd() * SIZE, y = rnd() * SIZE, r = 14 + rnd() * 46; ctx.beginPath();
    if (t.motif === "stars") { for (let k = 0; k < 10; k++) { const rr = k % 2 ? r * 0.45 : r; const a = (Math.PI / 5) * k - Math.PI / 2; ctx.lineTo(x + rr * Math.cos(a), y + rr * Math.sin(a)); } ctx.closePath(); }
    else if (t.motif === "diya") { ctx.ellipse(x, y, r, r * 0.6, 0, 0, Math.PI); ctx.moveTo(x, y - r * 0.2); ctx.quadraticCurveTo(x - r * 0.25, y - r * 0.9, x, y - r * 1.3); ctx.quadraticCurveTo(x + r * 0.25, y - r * 0.9, x, y - r * 0.2); }
    else ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1; ctx.textAlign = "center"; ctx.fillStyle = t.ink;
  // occasion
  ctx.font = `700 54px ${font}`; ctx.fillStyle = t.accent; ctx.fillText(occasion.toUpperCase().slice(0, 28), SIZE / 2, 150);
  // offer
  ctx.fillStyle = t.ink;
  if (pct > 0) {
    ctx.font = `900 330px ${font}`; ctx.fillText(`${pct}%`, SIZE / 2, 560);
    ctx.font = `800 120px ${font}`; ctx.fillStyle = t.accent; ctx.fillText(OFF[lang] || "OFF", SIZE / 2, 690);
  } else { ctx.font = `900 190px ${font}`; ctx.fillText(lang === "hi" ? "खास ऑफर" : "SPECIAL", SIZE / 2, 520); ctx.fillText(lang === "hi" ? "" : "OFFER", SIZE / 2, 690); }
  // shop + validity
  ctx.fillStyle = t.ink; ctx.font = `700 70px ${font}`;
  wrap(ctx, shop, SIZE - 160).forEach((l, i, a) => ctx.fillText(l, SIZE / 2, 830 + i * 76 - (a.length - 1) * 30));
  ctx.font = `500 44px ${font}`; ctx.globalAlpha = 0.92; ctx.fillText((VALID[lang] || VALID.en)(days), SIZE / 2, 1020); ctx.globalAlpha = 1;
}

export default function Poster({ shop, occasion, pct, days, lang, name }: { shop: string; occasion: string; pct: number; days: number; lang: string; name: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const run = () => ref.current && draw(ref.current, shop, occasion, pct, days, lang);
    run(); document.fonts?.ready.then(run).catch(() => {}); // redraw once fonts are available
  }, [shop, occasion, pct, days, lang]);
  const download = () => { const a = document.createElement("a"); a.download = `${name}-poster.png`; a.href = ref.current!.toDataURL("image/png"); a.click(); };
  return (
    <div>
      <canvas ref={ref} className="rounded-2xl w-full max-w-xs border border-line" role="img" aria-label={`Poster: ${occasion}${pct ? `, ${pct}% off` : ""} at ${shop}`} />
      <button className="btn btn-ghost mt-2" onClick={download}>Download PNG</button>
    </div>
  );
}
