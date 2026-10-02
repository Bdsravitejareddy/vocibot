"use client";

import { useEffect, useMemo, useState } from "react";
import { Languages, Search } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { getLanguageSettings, saveEnabledLanguages, type LanguageSettings } from "@/lib/languages";

export default function SettingsPage() {
  const [settings, setSettings] = useState<LanguageSettings | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { getLanguageSettings().then((loaded) => { setSettings(loaded); setSelected(loaded.enabled); }).catch((err) => setError(err instanceof Error ? err.message : "Unable to load settings.")); }, []);
  const visible = useMemo(() => (settings?.available ?? []).filter((language) => language.name.toLowerCase().includes(filter.trim().toLowerCase()) || language.code === filter.trim().toLowerCase()), [settings, filter]);
  const names = Object.fromEntries((settings?.available ?? []).map((language) => [language.code, language.name]));
  const changed = settings !== null && [...selected].sort().join() !== [...settings.enabled].sort().join();
  function toggle(code: string) { setMessage(""); setSelected((current) => current.includes(code) ? current.filter((item) => item !== code) : [...current, code]); }
  async function save() {
    if (selected.length === 0) return setError("Choose at least one language.");
    setSaving(true); setError(""); setMessage("");
    try { const saved = await saveEnabledLanguages(selected); setSettings(saved); setSelected(saved.enabled); setMessage("Saved. New consultations use these languages."); } catch (err) { setError(err instanceof Error ? err.message : "Unable to save."); } finally { setSaving(false); }
  }
  return <AppShell><div className="history-page settings-page">
    <div className="history-heading"><div><div className="eyebrow">Settings</div><h1>Consultation languages</h1><p>Tick the languages spoken in your clinic. Auto-detect only chooses among these, so it will not mistake Telugu for Kannada or Hindi for Urdu.</p></div><div className="history-count"><strong>{selected.length}</strong><span>enabled</span></div></div>
    {error && <div className="warning-banner" role="alert">{error}</div>}
    {message && <div className="notice-banner" role="status">{message}</div>}
    <section className="settings-card">
      <div className="settings-selected" data-testid="enabled-languages"><Languages size={16} /> {selected.length ? selected.map((code) => names[code] ?? code).join(", ") : "No languages selected"}</div>
      <label className="history-search"><Search size={15} /><input aria-label="Find a language" placeholder="Find a language" value={filter} onChange={(event) => setFilter(event.target.value)} /></label>
      <div className="language-grid">{visible.map((language) => <label className="language-option" key={language.code}><input type="checkbox" checked={selected.includes(language.code)} onChange={() => toggle(language.code)} /> {language.name}</label>)}</div>
      <div className="settings-actions"><button className="primary-button" onClick={() => void save()} disabled={!changed || saving || selected.length === 0}>{saving ? "Saving…" : "Save languages"}</button>{changed && <button className="secondary-button" onClick={() => setSelected(settings?.enabled ?? [])}>Undo changes</button>}</div>
    </section>
  </div></AppShell>;
}
