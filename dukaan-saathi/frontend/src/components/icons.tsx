import { useId } from "react";

// One outline icon family (24px grid, 1.9 stroke, round caps) so every glyph matches.
export const ICON_PATHS: Record<string, string> = {
  home: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  approvals: "M4 4h16v16H4zM8 12l3 3 5-6",
  stock: "M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10",
  box: "M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10",
  udhaar: "M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2zM5 18a2 2 0 0 1 2-2h12",
  book: "M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2zM5 18a2 2 0 0 1 2-2h12",
  customers: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 6.5M18 14.5a6.5 6.5 0 0 1 3.5 5.5",
  users: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 6.5M18 14.5a6.5 6.5 0 0 1 3.5 5.5",
  money: "M3 7a2 2 0 0 1 2-2h13v4M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2zM16 14.5h.01",
  wallet: "M3 7a2 2 0 0 1 2-2h13v4M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2zM16 14.5h.01",
  transactions: "M4 7h13l-3-3M20 17H7l3 3",
  growth: "M3 17l6-6 4 4 8-8M15 7h6v6",
  "trend-up": "M3 17l6-6 4 4 8-8M15 7h6v6",
  "trend-down": "M3 7l6 6 4-4 8 8M15 17h6v-6",
  marketing: "M3 10v4a1 1 0 0 0 1 1h2l5 4V5L6 9H4a1 1 0 0 0-1 1zM15 9a3 3 0 0 1 0 6M18 6a7 7 0 0 1 0 12",
  chat: "M4 5h16v11H9l-5 4zM8 10h8M8 13h5",
  shop: "M4 9l1.5-5h13L20 9M4 9v11h16V9M4 9a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0A2.7 2.7 0 0 0 20 9M10 20v-5h4v5",
  privacy: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  shield: "M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6zM8.5 12l2.5 2.5 4.5-5",
  check: "M5 12.5l4.5 4.5L19 7.5",
  "check-circle": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 12.5l2.8 2.8L16.5 9.5",
  x: "M6 6l12 12M18 6L6 18",
  "x-circle": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9 9l6 6M15 9l-6 6",
  tag: "M4 12V5h7l9 9-7 7-9-9zM8 8.5h.01",
  refund: "M4 12a8 8 0 1 0 3-6.2M4 4v4h4",
  refresh: "M20 12a8 8 0 1 1-3-6.2M20 4v4h-4",
  clock: "M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18",
  alert: "M12 4l9 16H3zM12 10v4M12 17h.01",
  doc: "M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6",
  file: "M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  bank: "M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18",
  search: "M16 16l4.5 4.5M11 17.5a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13z",
  chevron: "M6 9l6 6 6-6",
  "chevron-right": "M9 6l6 6-6 6",
  arrow: "M5 12h14M13 6l6 6-6 6",
  download: "M12 4v11m0 0l-4-4m4 4l4-4M5 20h14",
  logout: "M10 4H5v16h5M15 8l4 4-4 4M19 12H9",
  menu: "M4 7h16M4 12h16M4 17h16",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  send: "M4 12l16-8-6 16-2.5-6.5z",
  plus: "M12 5v14M5 12h14",
  volume: "M4 10v4h3l5 4V6L7 10zM16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11",
  stop: "M7 7h10v10H7z",
  sparkles: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8z",
  star: "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.9z",
  gift: "M4 10h16v10H4zM3 7h18v3H3zM12 7v13M12 7c-1.5-3-5-3.5-5-1s3 1 5 1zM12 7c1.5-3 5-3.5 5-1s-3 1-5 1z",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0",
  truck: "M3 6h11v10H3zM14 10h4l3 3v3h-7M7 19a2 2 0 1 0 0-.01M17 19a2 2 0 1 0 0-.01",
  inbox: "M4 13l2-8h12l2 8M4 13v6h16v-6M4 13h5l1 2h4l1-2h5",
  leaf: "M5 19c0-8 5-13 15-14-1 10-6 15-14 15M5 19l7-7",
  cart: "M3 4h2l2.4 11h10.2L20 8H6.2M9 20a1 1 0 1 0 0-.01M17 20a1 1 0 1 0 0-.01",
  pill: "M10.5 3.5a4.95 4.95 0 0 1 7 7l-7 7a4.95 4.95 0 0 1-7-7zM7 7l7 7",
  cake: "M4 20h16v-8H4zM4 15c2 1.5 3.5 1.5 5.3 0 1.8 1.5 3.6 1.5 5.4 0 1.8 1.5 3.3 1.5 5.3 0M12 12V8M12 5.5v.01",
  scissors: "M6 7a2.5 2.5 0 1 0 0-.01M6 17a2.5 2.5 0 1 0 0-.01M8 8.5L20 18M8 15.5L20 6",
  utensils: "M7 3v8M4.5 3v5a2.5 2.5 0 0 0 5 0V3M7 11v10M17 3c-2 1.5-3 4-3 7h3v11",
  store: "M4 9l1.5-5h13L20 9M4 9v11h16V9M4 9a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0A2.7 2.7 0 0 0 20 9M10 20v-5h4v5",
  hand: "M8 13V6a1.5 1.5 0 0 1 3 0v5M11 11V4.5a1.5 1.5 0 0 1 3 0V11M14 11V6a1.5 1.5 0 0 1 3 0v7c0 4-2.5 7-6 7s-5-2-6.5-4.5L3 13a1.5 1.5 0 0 1 2.5-1.5L8 14",
};

export function Icon({ name, size = 22, className = "", strokeWidth = 1.9 }: { name: string; size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d={ICON_PATHS[name] || ICON_PATHS.doc} />
    </svg>
  );
}

/** Brand mark: a rounded navy tile with a cyan spark. */
export function Logo({ size = 36 }: { size?: number }) {
  const id = `ds-g${useId().replace(/:/g, "")}`; // unique per instance: a hidden sidebar copy must not own the gradient
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#12408f" /><stop offset="1" stopColor="#0a6cdf" /></linearGradient>
      </defs>
      <rect width="40" height="40" rx="12" fill={`url(#${id})`} />
      <path d="M11 17l1.6-5h14.8L29 17M11 17v12h18V17M11 17a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M31 6l1 2.6 2.6 1-2.6 1L31 13l-1-2.4-2.6-1 2.6-1z" fill="#00d1ff" />
    </svg>
  );
}
