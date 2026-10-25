import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

const SUGGESTIONS = [
  "Will I lose power?",
  "How long could restoration take?",
  "What should I do to prepare?",
  "Do I qualify for outage alerts?",
  "Why is my risk this level?",
];

const OPS_SUGGESTIONS = [
  "Give me a briefing on this storm",
  "Which areas and circuits will be hit hardest?",
  "Do we have enough crews?",
  "What's the business impact?",
  "Are any life-support customers at risk?",
];

/** "Ask the Concierge" (customers, grounded on their own outage data) or the "Operations Copilot" (AEP, grounded on
 *  the system-wide model results) for the selected forecast / storm. */
export default function ChatWidget({ aep = false }) {
  const { scenario, scenarios, customerParams } = useApp();
  const [open, setOpen] = useState(false);
  const [threads, setThreads] = useState({}); // one conversation per forecast / storm
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const msgs = threads[scenario] || [];
  const sc = scenarios.find((s) => s.id === scenario);
  const title = aep ? "Operations Copilot" : "Ask the Concierge";

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs.length, busy, open]);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);

  async function send(q) {
    const content = (q ?? text).trim();
    if (!content || busy) return;
    const next = [...msgs, { role: "user", content }];
    setThreads((t) => ({ ...t, [scenario]: next }));
    setText("");
    setBusy(true);
    try {
      const r = await api(aep ? "/api/aep/chat" : "/api/me/chat", { method: "POST", body: { scenario, messages: next, access_mult: aep ? 1 : customerParams.access_mult } });
      setThreads((t) => ({ ...t, [scenario]: [...next, { role: "assistant", content: r.reply, source: r.source }] }));
    } catch (e) {
      setThreads((t) => ({ ...t, [scenario]: [...next, { role: "assistant", content: `Sorry - ${e.message}`, error: true }] }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {open && (
        <section className="chat-panel" role="dialog" aria-label={title}>
          <header className="chat-head">
            <div>
              <b>{title}</b>
              <div className="small" style={{ opacity: 0.85 }}>{scenario === "live" ? "Live 7-day forecast" : `Simulation: ${sc?.name}`}</div>
            </div>
            <button className="ghost" onClick={() => setOpen(false)} aria-label="Close chat">✕</button>
          </header>
          <div className="chat-body" aria-live="polite">
            {msgs.length === 0 && (
              <div className="stack">
                {aep ? (
                  <div className="bubble bot">I can brief you on the
                    {scenario === "live" ? " 7-day forecast" : ` simulated ${sc?.name?.toLowerCase()}`}: expected outages,
                    the hardest-hit ZIPs and circuits, crews and restoration time, costs and customer alerts.</div>
                ) : (
                  <div className="bubble bot">Hi! I can answer questions about your power, the
                    {scenario === "live" ? " coming week's forecast" : ` simulated ${sc?.name?.toLowerCase()}`}, restoration
                    and how to stay safe. What would you like to know?</div>
                )}
                <div className="chips">
                  {(aep ? OPS_SUGGESTIONS : SUGGESTIONS).map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`bubble ${m.role === "user" ? "me" : "bot"}${m.error ? " err" : ""}`}>
                {m.role === "assistant" ? <Markdown text={m.content} /> : m.content}
                {m.role === "assistant" && m.source === "template" && (
                  <div className="small muted" style={{ marginTop: 4 }}>Standard answer (AI unavailable)</div>
                )}
              </div>
            ))}
            {busy && <div className="bubble bot typing" aria-label="The assistant is typing"><i /><i /><i /></div>}
            <div ref={endRef} />
          </div>
          <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
              placeholder={aep ? "Ask about outages, crews, costs..." : "Ask about your power..."} aria-label="Your question" />
            <button className="primary" disabled={busy || !text.trim()}>Send</button>
          </form>
          <div className="chat-foot small muted">{aep
            ? "AI answers from the model results at the current settings - estimates for decision support. You decide."
            : "AI answers from your outage data - estimates, not guarantees. Emergency or downed line? Call 911."}</div>
        </section>
      )}
      <button className={`chat-fab${open ? " open" : ""}`} onClick={() => setOpen(!open)}
        aria-label={open ? `Close the ${title} chat` : title} aria-expanded={open}>
        {open ? "✕" : <><span aria-hidden="true">{aep ? "🛠️" : "💬"}</span> {title}</>}
      </button>
    </>
  );
}

/** Tiny, safe renderer for the AI's replies: **bold**, "- " bullet lists and paragraphs (no raw HTML). */
function Markdown({ text }) {
  const inline = (line) => line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    (part.startsWith("**") && part.endsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : part));
  const blocks = [];
  let list = null;
  text.split("\n").forEach((raw) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)/);
    if (bullet) {
      if (!list) { list = []; blocks.push({ list }); }
      list.push(bullet[1]);
    } else {
      list = null;
      if (line.trim()) blocks.push({ p: line });
    }
  });
  return blocks.map((bl, i) => (bl.list
    ? <ul key={i} className="chat-list">{bl.list.map((li, j) => <li key={j}>{inline(li)}</li>)}</ul>
    : <p key={i} className="chat-p">{inline(bl.p)}</p>));
}
