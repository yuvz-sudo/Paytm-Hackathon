import { useCallback, useEffect, useState } from "react";
import { api, authEvents, clearAuth, hasCredentials, isDemoMode, setDemo } from "./api";
import { useApi } from "./hooks";
import Home from "./pages/Home";
import Chat from "./pages/Chat";
import Approvals from "./pages/Approvals";
import Stock from "./pages/Stock";
import Udhaar from "./pages/Udhaar";
import Customers from "./pages/Customers";
import Money from "./pages/Money";
import Transactions from "./pages/Transactions";
import Privacy from "./pages/Privacy";
import MyShop from "./pages/MyShop";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Growth from "./pages/Growth";
import Marketing from "./pages/Marketing";
import { LangContext, tr } from "./i18n";
import { Icon, Logo } from "./components/icons";
import VoiceAssistant from "./components/VoiceAssistant";
import { LANGUAGES } from "./languages";
import { setUiLanguage } from "./translator";
import { stopSpeaking } from "./voice";

const TABS: [string, string, string][] = [
  ["home", "Today", "home"], ["chat", "Ask Saathi", "chat"], ["growth", "Growth Advisor", "growth"], ["marketing", "Marketing", "marketing"], ["approvals", "Approvals", "approvals"], ["stock", "Stock", "stock"], ["udhaar", "Udhaar", "udhaar"],
  ["customers", "Customers", "customers"], ["transactions", "Transactions", "transactions"], ["money", "Money & GST", "money"], ["shop", "My Shop", "shop"], ["privacy", "Privacy", "privacy"],
];
// Menu sections, collapsible like the Paytm for Business drawer
const GROUPS: [string, string[]][] = [
  ["Dashboard", ["home", "transactions", "growth", "marketing", "chat", "approvals"]],
  ["Run your shop", ["stock", "udhaar", "customers", "money"]],
  ["Settings", ["shop", "privacy"]],
];
const SUBTITLE: Record<string, string> = {
  transactions: "Every payment you received, today and yesterday",
  marketing: "Create offers and posters, then see how they did",
  growth: "Your business and money advisor: season stock, slow sellers, cash and market prices",
  chat: "Ask in any Indian language, by voice or text", approvals: "Review drafts, then send them from your own WhatsApp in one tap",
  stock: "What’s running low and what to reorder", udhaar: "Who owes you, and gentle reminders", customers: "Regulars, new faces and who stopped coming",
  money: "Settlements, cash flow, credit and GST", shop: "Your shop details, items and suppliers", privacy: "Choose what Saathi is allowed to read",
};

const KEYWORDS: Record<string, string[]> = {
  home: ["briefing", "sales", "dashboard", "overview"], approvals: ["approve", "pending"], stock: ["inventory", "reorder", "supplier"],
  udhaar: ["credit", "ledger", "dues", "khata"], customers: ["customer", "loyalty", "offer"],
  transactions: ["payment", "payments", "txn", "upi", "collection", "received"], money: ["gst", "tax", "settlement", "loan", "cash", "refund"], shop: ["profile", "settings", "items"], privacy: ["consent", "data"],
};

type Phase = "loading" | "login" | "onboarding" | "app";

export default function App() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [profile, setProfile] = useState<any>(null);

  const bootstrap = useCallback(async () => {
    if (!hasCredentials()) { setPhase("login"); return; }
    try {
      const me = await api("/auth/me");
      setProfile(me);
      setPhase(me.onboarded ? "app" : "onboarding");
    } catch { clearAuth(); setPhase("login"); }
  }, []);

  useEffect(() => { bootstrap(); }, [bootstrap]);
  useEffect(() => { if (phase === "login") setUiLanguage("en"); }, [phase]);
  useEffect(() => {
    const out = () => { clearAuth(); setPhase("login"); };
    const onb = () => setPhase("onboarding");
    authEvents.addEventListener("unauthorized", out);
    authEvents.addEventListener("onboarding", onb);
    return () => { authEvents.removeEventListener("unauthorized", out); authEvents.removeEventListener("onboarding", onb); };
  }, []);

  const logout = async () => { stopSpeaking(); setUiLanguage("en"); try { await api("/auth/logout", { method: "POST" }); } catch { /* ignore */ } clearAuth(); setProfile(null); setPhase("login"); };

  if (phase === "loading") return (
    <div className="min-h-full grid place-items-center" role="status">
      <div className="flex flex-col items-center gap-4"><span className="animate-pulse"><Logo size={56} /></span><span className="text-sm font-semibold text-muted">Loading Dukaan Saathi…</span></div>
    </div>);
  if (phase === "login") return <Login onDone={bootstrap} />;
  if (phase === "onboarding") return <Onboarding onDone={bootstrap} onLogout={logout} />;
  return <Shell profile={profile} reloadProfile={bootstrap} logout={logout} />;
}

function Shell({ profile, reloadProfile, logout }: { profile: any; reloadProfile: () => void; logout: () => void }) {
  const [tab, setTab] = useState<string>(() => new URLSearchParams(location.search).get("tab") || localStorage.getItem("tab") || "home");
  const [lang, setLang] = useState(profile.language);
  const [version, setVersion] = useState(0); // bump to remount pages after consent / data / language changes
  const demo = isDemoMode();
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [searchFocus, setSearchFocus] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ Dashboard: true, "Run your shop": true, Settings: true });
  const [bannerHidden, setBannerHidden] = useState(false);
  const merchants = useApi<any[]>(demo ? "/merchants" : null);
  const pending = useApi<any[]>("/actions?status=pending", [version, tab]);

  useEffect(() => { localStorage.setItem("tab", tab); }, [tab]);
  useEffect(() => {
    if (!menuOpen && !profileOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setMenuOpen(false); setProfileOpen(false); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen, profileOpen]);
  useEffect(() => { setLang(profile.language); }, [profile.language]);
  useEffect(() => { setUiLanguage(lang); }, [lang]);

  const switchDemo = (id: number) => { setDemo(id); localStorage.setItem("tab", "home"); location.reload(); };
  const changeLang = async (l: string) => { setLang(l); try { await api("/merchant/language", { method: "PUT", body: { language: l } }); setVersion((v) => v + 1); } catch { /* keep UI language */ } };
  const loadSample = async () => { try { await api("/onboarding/sample-data", { method: "POST" }); reloadProfile(); setVersion((v) => v + 1); } catch { /* shown on My Shop */ go("shop"); } };

  // go("transactions:yesterday") opens a page with an argument (which day / which filter)
  const [tabArg, setTabArg] = useState("");
  const go = useCallback((target: string) => {
    const i = target.indexOf(":");
    setTab(i < 0 ? target : target.slice(0, i));
    setTabArg(i < 0 ? "" : target.slice(i + 1));
  }, []);
  const pick = (id: string) => { go(id); setMenuOpen(false); };
  // Header search jumps to the matching section; anything else goes to Ask Saathi.
  const matches = (q: string) => TABS.filter(([id, label]) => id.includes(q) || label.toLowerCase().includes(q) || (KEYWORDS[id] || []).some((k) => k.includes(q) || q.includes(k)));
  const suggestions = query.trim() ? matches(query.trim().toLowerCase()) : [];
  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim().toLowerCase();
    if (!q) return;
    const hit = matches(q)[0];
    go(hit ? hit[0] : "chat");
    setQuery(""); setSearchFocus(false);
  };

  const body = () => {
    switch (tab) {
      case "home": return <Home go={go} lang={lang} onSample={loadSample} />;
      case "chat": return <Chat lang={lang} merchantId={profile.id} initial={tabArg} />;
      case "growth": return <Growth go={go} lang={lang} />;
      case "marketing": return <Marketing go={go} shop={profile.name} lang={lang} />;
      case "approvals": return <Approvals go={go} />;
      case "stock": return <Stock go={go} />;
      case "udhaar": return <Udhaar go={go} />;
      case "customers": return <Customers go={go} />;
      case "transactions": return <Transactions go={go} arg={tabArg} />;
      case "money": return <Money go={go} />;
      case "shop": return <MyShop profile={profile} refreshProfile={() => { reloadProfile(); setVersion((v) => v + 1); }} />;
      case "privacy": return <Privacy onChange={() => setVersion((v) => v + 1)} />;
      default: return null;
    }
  };

  const isHome = tab === "home";
  const tabLabel = TABS.find(([id]) => id === tab)?.[1] || "";
  const tabIcon = TABS.find(([id]) => id === tab)?.[2] || "home";
  const initial = (profile.name || "?").trim()[0]?.toUpperCase();
  const pendingCount = pending.data?.length ?? 0;
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const signOut = () => { setProfileOpen(false); demo ? (clearAuth(), location.reload()) : logout(); };

  const nav = (
    <nav className="flex-1 overflow-y-auto px-3 pb-4" aria-label="Main">
      {GROUPS.map(([group, ids]) => (
        <div key={group} className="mt-3 first:mt-1">
          <button onClick={() => setOpenGroups((g) => ({ ...g, [group]: !g[group] }))} aria-expanded={openGroups[group]}
            className="w-full flex items-center justify-between px-3 py-2 text-[11px] font-bold uppercase tracking-[.08em] text-sky-200/70 hover:text-sky-100">
            {tr(lang, group)}<span className={`transition-transform ${openGroups[group] ? "" : "-rotate-90"}`}><Icon name="chevron" size={15} /></span>
          </button>
          {openGroups[group] && ids.map((id) => {
            const [, label, icon] = TABS.find(([x]) => x === id)!;
            const active = tab === id;
            return (
              <button key={id} onClick={() => pick(id)} aria-current={active ? "page" : undefined}
                className={`relative w-full flex items-center gap-3 rounded-xl px-3 py-2.5 my-0.5 text-[14px] text-left transition-colors ${active ? "bg-white/[.12] text-white font-bold shadow-[inset_0_0_0_1px_rgba(255,255,255,.08)]" : "text-sky-50/80 font-medium hover:bg-white/[.06] hover:text-white"}`}>
                {active && <span className="absolute -left-3 top-2 bottom-2 w-1 rounded-r-full bg-accent shadow-[0_0_12px_rgba(0,185,245,.8)]" aria-hidden />}
                <span className={active ? "text-accent" : "text-sky-200/80"}><Icon name={icon} size={20} /></span>{tr(lang, label)}
                {id === "approvals" && pendingCount > 0 && <span className="ml-auto rounded-full bg-accent text-brand text-[11px] font-extrabold px-2 py-0.5 tabular-nums" aria-label={`${pendingCount} pending`}>{pendingCount}</span>}
              </button>);
          })}
        </div>))}
    </nav>
  );
  const brandBlock = (
    <button onClick={() => pick("home")} className="flex items-center gap-3 text-left" aria-label="Dukaan Saathi home" translate="no">
      <Logo size={38} />
      <span className="leading-tight"><span className="block text-[17px] font-extrabold tracking-tight text-white">Dukaan <span className="text-accent">Saathi</span></span>
        <span className="block text-[11px] font-semibold text-sky-200/70">AI partner for Paytm merchants</span></span>
    </button>
  );
  const sidebarSkin = "bg-[linear-gradient(180deg,#0b2a5b_0%,#0a2350_60%,#081b3f_100%)] text-white";
  const userBlock = (
    <div className="m-3 rounded-2xl bg-white/[.06] ring-1 ring-white/10 p-3 flex items-center gap-3">
      <span className="h-10 w-10 shrink-0 rounded-full bg-gradient-to-br from-accent to-primary grid place-items-center font-extrabold text-white">{initial}</span>
      <div className="min-w-0 flex-1" translate="no"><p className="text-sm font-bold truncate">{profile.name}</p><p className="text-[11.5px] text-sky-200/70 truncate">{profile.owner} · {profile.city}</p></div>
      <button onClick={signOut} aria-label={demo ? "Exit demo" : "Sign out"} title={demo ? "Exit demo" : "Sign out"} className="h-9 w-9 grid place-items-center rounded-xl text-sky-200/80 hover:bg-white/10 hover:text-white"><Icon name="logout" size={18} /></button>
    </div>
  );
  const BOTTOM: [string, string, string][] = [["home", "Today", "home"], ["chat", "Ask Saathi", "chat"], ["approvals", "Approvals", "approvals"], ["udhaar", "Udhaar", "udhaar"]];

  return (
    <LangContext.Provider value={lang}>
      <div className="min-h-full lg:pl-[272px]">
        {/* Desktop sidebar */}
        <aside className={`hidden lg:flex fixed inset-y-0 left-0 z-30 w-[272px] flex-col ${sidebarSkin}`} aria-label="Sidebar">
          <div className="px-5 h-[72px] flex items-center shrink-0">{brandBlock}</div>
          {nav}
          {userBlock}
        </aside>

        {/* Mobile drawer */}
        <div className={`scrim lg:hidden fixed inset-0 z-40 bg-slate-950/50 backdrop-blur-[2px] ${menuOpen ? "opacity-100 visible" : "opacity-0 invisible"}`} onClick={() => setMenuOpen(false)} aria-hidden />
        <aside className={`drawer lg:hidden fixed inset-y-0 left-0 z-50 w-[288px] max-w-[86vw] shadow-2xl flex flex-col ${sidebarSkin} ${menuOpen ? "translate-x-0 visible" : "-translate-x-full invisible"}`} aria-label="Menu" aria-hidden={!menuOpen}>
          <div className="flex items-center justify-between px-5 h-[72px] shrink-0">
            {brandBlock}
            <button onClick={() => setMenuOpen(false)} aria-label="Close menu" className="h-10 w-10 -mr-2 grid place-items-center rounded-xl text-sky-200 hover:bg-white/10"><Icon name="x" size={20} /></button>
          </div>
          {nav}
          {userBlock}
        </aside>

        <header className="sticky top-0 z-30 bg-white/75 backdrop-blur-xl border-b border-line/80">
          <div className="mx-auto w-full max-w-[1240px] h-16 px-4 lg:px-8 flex items-center gap-3">
            <button onClick={() => setMenuOpen(true)} aria-label="Open menu" aria-expanded={menuOpen} className="lg:hidden h-10 w-10 -ml-1 grid place-items-center rounded-xl text-brand hover:bg-surface">
              <Icon name="menu" size={22} />
            </button>
            <button onClick={() => go("home")} className="lg:hidden shrink-0" aria-label="Dukaan Saathi home"><Logo size={32} /></button>
            <div className="relative flex-1 min-w-0 max-w-xl">
              <form role="search" onSubmit={onSearch} className="flex items-center gap-2 rounded-full border border-line bg-surface/80 pl-4 pr-1.5 h-11 transition-colors focus-within:border-primary focus-within:bg-white focus-within:shadow-[0_0_0_4px_rgba(10,108,223,.1)]">
                <span className="text-muted"><Icon name="search" size={18} /></span>
                <input value={query} onChange={(e) => setQuery(e.target.value)} onFocus={() => setSearchFocus(true)} onBlur={() => setTimeout(() => setSearchFocus(false), 120)} aria-label="Search for a topic" placeholder="Search or ask Saathi…" className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted" />
                <kbd className="hidden md:inline-flex items-center rounded-md border border-line bg-white px-1.5 py-0.5 text-[10.5px] font-semibold text-muted">Enter</kbd>
              </form>
              {searchFocus && query.trim() && (
                <ul className="pop absolute left-0 right-0 top-[52px] z-40 rounded-2xl bg-white border border-line shadow-[var(--shadow-lift)] p-1.5" role="listbox">
                  {suggestions.length === 0
                    ? <li><button onMouseDown={(e) => e.preventDefault()} onClick={() => { go("chat"); setQuery(""); }} className="w-full flex items-center gap-3 text-left rounded-xl px-3 py-2.5 text-sm hover:bg-surface"><span className="icon-tile !h-8 !w-8 !rounded-lg bg-sky-50 text-primary"><Icon name="sparkles" size={16} /></span><span>Ask Saathi: <b>“{query.trim()}”</b></span></button></li>
                    : suggestions.map(([id, label, icon]) => (
                      <li key={id}><button onMouseDown={(e) => e.preventDefault()} onClick={() => { go(id); setQuery(""); setSearchFocus(false); }} className="w-full flex items-center gap-3 text-left rounded-xl px-3 py-2.5 text-sm font-medium hover:bg-surface"><span className="icon-tile !h-8 !w-8 !rounded-lg bg-sky-50 text-primary"><Icon name={icon} size={16} /></span>{tr(lang, label)}<span className="ml-auto text-muted"><Icon name="chevron-right" size={16} /></span></button></li>))}
                </ul>)}
            </div>
            <div className="ml-auto flex items-center gap-2">
              {demo && (
                <select className="pill-select hidden md:block max-w-[200px]" value={profile.id} onChange={(e) => switchDemo(Number(e.target.value))} aria-label="Switch demo merchant">
                  {(merchants.data || []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>)}
              <select className="pill-select hidden sm:block max-w-[180px]" value={lang} onChange={(e) => changeLang(e.target.value)} aria-label="Language">
                {LANGUAGES.map(([v, l, en]) => <option key={v} value={v}>{l === en ? l : `${l} · ${en}`}</option>)}
              </select>
              <button onClick={() => go("approvals")} aria-label={`Approvals${pendingCount ? `, ${pendingCount} pending` : ""}`} className="relative h-10 w-10 grid place-items-center rounded-full border border-line bg-white text-brand hover:bg-surface">
                <Icon name="bell" size={19} />
                {pendingCount > 0 && <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-extrabold grid place-items-center ring-2 ring-white tabular-nums" aria-hidden>{pendingCount}</span>}
              </button>
              <div className="relative shrink-0">
                <button onClick={() => setProfileOpen((v) => !v)} aria-label="Account menu" aria-expanded={profileOpen} className="h-10 w-10 rounded-full bg-gradient-to-br from-accent to-primary grid place-items-center font-extrabold text-sm text-white shadow-[var(--shadow-glow)] hover:brightness-110">{initial}</button>
                {profileOpen && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setProfileOpen(false)} aria-hidden />
                    <div className="pop absolute right-0 top-12 z-40 w-72 rounded-2xl bg-white border border-line shadow-[var(--shadow-lift)] p-2" style={{ transformOrigin: "top right" }}>
                      <div className="px-3 py-3 border-b border-line mb-1 flex items-center gap-3" translate="no">
                        <span className="h-10 w-10 shrink-0 rounded-full bg-gradient-to-br from-accent to-primary grid place-items-center font-extrabold text-white">{initial}</span>
                        <div className="min-w-0"><p className="font-bold text-sm truncate">{profile.name}</p><p className="text-xs text-muted truncate">{profile.owner} · {profile.city}</p></div>
                      </div>
                      <label className="sm:hidden block px-3 py-2 text-xs font-semibold text-muted">Language
                        <select className="pill-select mt-1 w-full" value={lang} onChange={(e) => changeLang(e.target.value)}>
                          {LANGUAGES.map(([v, l, en]) => <option key={v} value={v}>{l === en ? l : `${l} · ${en}`}</option>)}
                        </select></label>
                      {demo && (
                        <label className="md:hidden block px-3 py-2 text-xs font-semibold text-muted">Demo shop
                          <select className="pill-select mt-1 w-full" value={profile.id} onChange={(e) => switchDemo(Number(e.target.value))}>
                            {(merchants.data || []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                          </select></label>)}
                      <button onClick={() => { setProfileOpen(false); go("shop"); }} className="w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium hover:bg-surface text-left"><Icon name="shop" size={18} />My Shop</button>
                      <button onClick={() => { setProfileOpen(false); go("privacy"); }} className="w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium hover:bg-surface text-left"><Icon name="shield" size={18} />Privacy</button>
                      <div className="my-1 border-t border-line" />
                      <button onClick={signOut} className="w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-red-600 hover:bg-red-50 text-left"><Icon name="logout" size={18} />{demo ? "Exit demo" : "Sign out"}</button>
                    </div>
                  </>)}
              </div>
            </div>
          </div>
        </header>

        <main className="min-w-0">
          {(profile.sample_data && !demo && !bannerHidden) && (
            <div className="mx-auto max-w-[1240px] px-4 lg:px-8 pt-4">
              <div className="rounded-2xl bg-emerald-50 ring-1 ring-emerald-200 text-emerald-900 text-sm px-4 py-3 flex items-start gap-3">
                <span className="icon-tile !h-9 !w-9 !rounded-xl bg-white text-emerald-600"><Icon name="sparkles" size={18} /></span>
                <div className="flex-1"><p className="font-bold">You’re viewing sample data</p><p className="text-xs mt-0.5">These payments are simulated. <button className="underline font-semibold" onClick={() => go("shop")}>Manage in My Shop</button></p></div>
                <button onClick={() => setBannerHidden(true)} aria-label="Dismiss" className="h-8 w-8 grid place-items-center rounded-lg text-emerald-800/70 hover:bg-emerald-100"><Icon name="x" size={16} /></button>
              </div>
            </div>)}
          <div className="mx-auto w-full max-w-[1240px] px-4 lg:px-8 pt-7 pb-36 lg:pb-28">
            <div className="flex flex-wrap items-end justify-between gap-4 mb-7">
              <div className="min-w-0 flex items-center gap-4">
                {!isHome && <span className="hidden sm:grid icon-tile !h-12 !w-12 !rounded-2xl bg-white text-primary ring-1 ring-line shadow-[var(--shadow-card)]"><Icon name={tabIcon} size={24} /></span>}
                <div className="min-w-0">
                  {isHome && <p className="text-[13px] font-semibold text-primary">{greeting}, <span translate="no">{(profile.owner || "").split(" ")[0]}</span></p>}
                  <h1 className="text-[28px] sm:text-[34px] font-extrabold tracking-tight text-ink leading-tight" translate={isHome ? "no" : undefined}>{isHome ? profile.name : tr(lang, tabLabel)}</h1>
                  {isHome
                    ? <div className="flex flex-wrap gap-2 mt-2">{[profile.city, profile.segment].filter(Boolean).map((x: string) => <span key={x} className="rounded-full bg-white ring-1 ring-line px-3 py-1 text-xs font-semibold text-muted capitalize">{x}</span>)}</div>
                    : <p className="text-sm mt-1 text-muted">{SUBTITLE[tab] || profile.name}</p>}
                </div>
              </div>
            </div>
            <div key={`${profile.id}-${version}-${tab}-${tabArg}`} className="page-enter">{body()}</div>
          </div>
        </main>

        {/* Mobile bottom navigation */}
        <nav className="lg:hidden fixed bottom-0 inset-x-0 z-30 bg-white/90 backdrop-blur-xl border-t border-line pb-[env(safe-area-inset-bottom)]" aria-label="Quick">
          <div className="grid grid-cols-5 h-16">
            {BOTTOM.map(([id, label, icon]) => {
              const active = tab === id;
              return (
                <button key={id} onClick={() => go(id)} aria-current={active ? "page" : undefined} className={`relative flex flex-col items-center justify-center gap-1 text-[11px] font-semibold ${active ? "text-primary" : "text-muted"}`}>
                  <span className={`grid place-items-center h-7 w-12 rounded-full transition-colors ${active ? "bg-sky-100" : ""}`}><Icon name={icon} size={20} /></span>{tr(lang, label)}
                  {id === "approvals" && pendingCount > 0 && <span className="absolute top-1.5 right-[22%] h-2 w-2 rounded-full bg-red-500 ring-2 ring-white" aria-hidden />}
                </button>);
            })}
            <button onClick={() => setMenuOpen(true)} className="flex flex-col items-center justify-center gap-1 text-[11px] font-semibold text-muted">
              <span className="grid place-items-center h-7 w-12 rounded-full"><Icon name="grid" size={20} /></span>More
            </button>
          </div>
        </nav>
        {tab !== "chat" && <VoiceAssistant lang={lang} go={go} tab={tab} />}
      </div>
    </LangContext.Provider>
  );
}
