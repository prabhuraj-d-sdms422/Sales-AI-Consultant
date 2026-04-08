import { useEffect, useRef, useState } from "react";
import { createSession, endSession, getApiBase, getSessionConfig, saveProfile } from "../utils/api.js";
import { useChat } from "../hooks/useChat.js";
import MessageBubble from "./MessageBubble.jsx";
import TypingIndicator from "./TypingIndicator.jsx";
import TokenUsagePanel from "./TokenUsagePanel.jsx";

const CHAT_SESSION_ID_KEY = "stark.chat.sessionId";
const CHAT_MESSAGES_KEY = "stark.chat.messages";
const CHAT_FORM_SHOWN_KEY = "stark.chat.formShown";
const CHAT_TIMINGS_KEY = "stark.chat.timings";

function getNavigationType() {
  try {
    const navEntries = performance.getEntriesByType?.("navigation");
    if (navEntries && navEntries[0]?.type) return navEntries[0].type;
  } catch {
    // ignore
  }
  // Fallback for older browsers (deprecated but still widely supported).
  // 1 = reload, 2 = back_forward, 0 = navigate
  // eslint-disable-next-line no-restricted-globals
  const legacy = performance?.navigation?.type;
  if (legacy === 1) return "reload";
  if (legacy === 2) return "back_forward";
  return "navigate";
}

function beaconEndSession(sessionId) {
  try {
    if (!sessionId) return;
    const url = `${getApiBase()}/session/end`;
    const blob = new Blob([JSON.stringify({ session_id: sessionId })], {
      type: "application/json",
    });
    navigator.sendBeacon(url, blob);
  } catch {
    // ignore
  }
}

export default function ChatWidget() {
  const [sessionId, setSessionId] = useState(null);
  const [input, setInput] = useState("");
  const [ended, setEnded] = useState(false);
  const [timings, setTimings] = useState({ promptMin: 10, endMin: 20 });
  const [showIdlePrompt, setShowIdlePrompt] = useState(false);
  const [formShown, setFormShown] = useState(false);
  const [contactForm, setContactForm] = useState({ name: "", email: "", phone: "", location: "" });

  const { messages, streamingText, isTyping, tokenUsage, lastSources, error, sendMessage } =
    useChat(sessionId, setSessionId);
  const listRef = useRef(null);
  const lastActivityRef = useRef(Date.now());
  const idlePromptTimerRef = useRef(null);
  const idleEndTimerRef = useRef(null);
  // Tracks whether we already fired an explicit /session/end from this client.
  // Prevents the beforeunload beacon from firing a second delivery after an explicit end.
  const explicitlyEndedRef = useRef(false);
  // Always holds the latest sessionId so the beforeunload handler can read it.
  const sessionIdRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const navType = typeof window !== "undefined" ? getNavigationType() : "navigate";
      if (navType === "reload") {
        try {
          const existing = window.sessionStorage.getItem(CHAT_SESSION_ID_KEY);
          if (existing) {
            explicitlyEndedRef.current = true;
            beaconEndSession(existing);
          }
          window.sessionStorage.removeItem(CHAT_SESSION_ID_KEY);
          window.sessionStorage.removeItem(CHAT_MESSAGES_KEY);
          window.sessionStorage.removeItem(CHAT_FORM_SHOWN_KEY);
          window.sessionStorage.removeItem(CHAT_TIMINGS_KEY);
        } catch {
          // ignore
        }
      }

      try {
        const existing = window.sessionStorage.getItem(CHAT_SESSION_ID_KEY);
        if (existing) {
          if (!cancelled) setSessionId(existing);
          try {
            const tRaw = window.sessionStorage.getItem(CHAT_TIMINGS_KEY);
            if (tRaw) {
              const parsed = JSON.parse(tRaw);
              if (parsed && typeof parsed === "object") {
                setTimings({
                  promptMin: Number(parsed.promptMin || 10),
                  endMin: Number(parsed.endMin || 20),
                });
              }
            } else {
              // No cached timings (e.g. older sessions) — fetch from backend config.
              const cfg = await getSessionConfig();
              const newTimings = {
                promptMin: Number(cfg?.inactivity_prompt_minutes || 10),
                endMin: Number(cfg?.inactivity_end_minutes || 20),
              };
              if (!cancelled) setTimings(newTimings);
              try {
                window.sessionStorage.setItem(CHAT_TIMINGS_KEY, JSON.stringify(newTimings));
              } catch {
                // ignore
              }
            }
          } catch {
            // ignore
          }
          try {
            const fs = window.sessionStorage.getItem(CHAT_FORM_SHOWN_KEY);
            if (!cancelled) setFormShown(fs === "1");
          } catch {
            // ignore
          }
          return;
        }
      } catch {
        // ignore
      }

      try {
        const data = await createSession();
        if (cancelled) return;
        setSessionId(data.session_id);
        const newTimings = {
          promptMin: Number(data.inactivity_prompt_minutes || 10),
          endMin: Number(data.inactivity_end_minutes || 20),
        };
        setTimings(newTimings);
        try {
          window.sessionStorage.setItem(CHAT_SESSION_ID_KEY, data.session_id);
          window.sessionStorage.setItem(CHAT_TIMINGS_KEY, JSON.stringify(newTimings));
        } catch {
          // ignore
        }
      } catch {
        if (!cancelled) setSessionId(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Keep ref in sync so the stable beforeunload handler always sees the latest sessionId.
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  // End session reliably on tab close / navigation away / SPA unmount.
  // Registered once — uses refs so it never needs to be re-registered.
  useEffect(() => {
    if (typeof window === "undefined") return;

    const handleUnload = () => {
      // Only beacon if we haven't already explicitly ended this session from the UI.
      if (!explicitlyEndedRef.current && sessionIdRef.current) {
        beaconEndSession(sessionIdRef.current);
      }
    };

    window.addEventListener("beforeunload", handleUnload);
    return () => {
      window.removeEventListener("beforeunload", handleUnload);
      // SPA unmount — same guard: only send if not already explicitly ended.
      if (!explicitlyEndedRef.current && sessionIdRef.current) {
        beaconEndSession(sessionIdRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Keep the newest streamed token visible.
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, streamingText, isTyping]);

  // Inactivity UX: show prompt after N minutes, auto-end after +M minutes.
  useEffect(() => {
    if (!sessionId || ended) return;
    if (typeof window === "undefined") return;

    if (idlePromptTimerRef.current) window.clearTimeout(idlePromptTimerRef.current);
    if (idleEndTimerRef.current) window.clearTimeout(idleEndTimerRef.current);

    const promptMs = Math.max(1, timings.promptMin) * 60 * 1000;
    const endMs = Math.max(1, timings.endMin) * 60 * 1000;
    const now = Date.now();
    const sinceLast = now - lastActivityRef.current;

    const promptIn = Math.max(0, promptMs - sinceLast);
    idlePromptTimerRef.current = window.setTimeout(() => {
      setShowIdlePrompt(true);
      idleEndTimerRef.current = window.setTimeout(async () => {
        explicitlyEndedRef.current = true;
        try {
          await endSession(sessionId);
        } catch {
          // ignore
        } finally {
          setEnded(true);
          setShowIdlePrompt(false);
          try {
            window.sessionStorage.removeItem(CHAT_SESSION_ID_KEY);
            window.sessionStorage.removeItem(CHAT_MESSAGES_KEY);
            window.sessionStorage.removeItem(CHAT_FORM_SHOWN_KEY);
            window.sessionStorage.removeItem(CHAT_TIMINGS_KEY);
          } catch {
            // ignore
          }
        }
      }, endMs);
    }, promptIn);

    return () => {
      if (idlePromptTimerRef.current) window.clearTimeout(idlePromptTimerRef.current);
      if (idleEndTimerRef.current) window.clearTimeout(idleEndTimerRef.current);
    };
  }, [sessionId, ended, timings.promptMin, timings.endMin, messages.length]);

  // (form trigger is derived below — no effect needed)

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || !sessionId) return;
    if (ended) return;
    const t = input;
    setInput("");
    lastActivityRef.current = Date.now();
    setShowIdlePrompt(false);
    await sendMessage(t);
  };

  const onEndChat = async () => {
    if (!sessionId) return;
    // Mark as explicitly ended BEFORE the fetch so the beforeunload beacon is suppressed
    // even if the user closes the tab while the request is in-flight.
    explicitlyEndedRef.current = true;
    try {
      await endSession(sessionId);
    } catch {
      // ignore — backend idempotency covers any retry
    } finally {
      setEnded(true);
      setShowIdlePrompt(false);
      try {
        window.sessionStorage.removeItem(CHAT_SESSION_ID_KEY);
        window.sessionStorage.removeItem(CHAT_MESSAGES_KEY);
        window.sessionStorage.removeItem(CHAT_FORM_SHOWN_KEY);
        window.sessionStorage.removeItem(CHAT_TIMINGS_KEY);
      } catch {
        // ignore
      }
    }
  };

  const onIdleContinue = () => {
    lastActivityRef.current = Date.now();
    setShowIdlePrompt(false);
  };

  const onIdleEnd = async () => {
    await onEndChat();
  };

  const markFormShown = () => {
    setFormShown(true);
    try {
      window.sessionStorage.setItem(CHAT_FORM_SHOWN_KEY, "1");
    } catch {
      // ignore
    }
  };

  // Show form only after the user has sent their first message.
  // This way the greeting appears clean and the form surfaces naturally mid-conversation.
  const shouldShowContactForm =
    !!sessionId &&
    !ended &&
    !formShown &&
    messages.some((m) => m.role === "user");

  // While the form is visible we hold back any AI reply that arrived during form filling.
  // Only show messages up to (and including) the first user message so the response is
  // revealed all at once after the form is submitted.
  const firstUserIdx = messages.findIndex((m) => m.role === "user");
  const visibleMessages = shouldShowContactForm && firstUserIdx >= 0
    ? messages.slice(0, firstUserIdx + 1)
    : messages;

  const contactFormComplete =
    (contactForm.name || "").trim() &&
    (contactForm.email || "").trim() &&
    (contactForm.phone || "").trim() &&
    (contactForm.location || "").trim();

  const submitContactForm = async () => {
    try {
      const payload = {
        name: (contactForm.name || "").trim() || null,
        email: (contactForm.email || "").trim() || null,
        phone: (contactForm.phone || "").trim() || null,
        location: (contactForm.location || "").trim() || null,
      };
      await saveProfile(sessionId, payload);
    } catch {
      // ignore
    } finally {
      markFormShown();
    }
  };

  return (
    <div className="flex flex-col h-full w-full bg-white/[0.02] border border-white/10 rounded-2xl overflow-hidden backdrop-blur">
      <header className="px-4 py-3 border-b border-white/10 bg-transparent">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-stark-blue/20 border border-stark-blue/30" />
          <div>
            <h1 className="text-base font-semibold text-slate-100">
              Stark Digital
            </h1>
            <p className="text-xs text-slate-400">
              AI Sales Consultant — how can we help?
            </p>
          </div>
          <div className="ml-auto">
            <button
              type="button"
              onClick={onEndChat}
              disabled={!sessionId || ended}
              className="text-xs rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-slate-200 hover:bg-white/[0.06] disabled:opacity-40"
            >
              End chat
            </button>
          </div>
        </div>
      </header>
      <TokenUsagePanel tokenUsage={tokenUsage} />
      <div
        ref={listRef}
        className="flex-1 overflow-y-auto px-4 sm:px-6 py-6 space-y-4"
      >
        {!sessionId && (
          <p className="text-slate-500 text-sm">Starting session…</p>
        )}
        {visibleMessages.map((m, i) => (
          <MessageBubble key={i} role={m.role}>
            {m.content}
          </MessageBubble>
        ))}

        {/* While the contact form is visible: show a "preparing response" animation
            so the user knows a reply is being assembled. The actual response is held
            back and revealed in full right after the form is submitted. */}
        {shouldShowContactForm && (
          <MessageBubble role="assistant">
            <div className="flex items-center gap-2.5">
              <TypingIndicator />
              <span className="text-xs text-slate-500 italic">Preparing your response…</span>
            </div>
          </MessageBubble>
        )}

        {shouldShowContactForm && (
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <div className="text-sm text-slate-200 font-medium">
              While we get your response ready, mind sharing your details so we can follow up personally?
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2">
              <input
                value={contactForm.name}
                onChange={(e) => setContactForm((p) => ({ ...p, name: e.target.value }))}
                placeholder="Name"
                className="w-full rounded-xl bg-black/30 border border-white/10 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
              />
              <input
                value={contactForm.email}
                onChange={(e) => setContactForm((p) => ({ ...p, email: e.target.value }))}
                placeholder="Email"
                className="w-full rounded-xl bg-black/30 border border-white/10 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
              />
              <input
                value={contactForm.phone}
                onChange={(e) => setContactForm((p) => ({ ...p, phone: e.target.value }))}
                placeholder="Phone"
                className="w-full rounded-xl bg-black/30 border border-white/10 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
              />
              <input
                value={contactForm.location}
                onChange={(e) => setContactForm((p) => ({ ...p, location: e.target.value }))}
                placeholder="Location"
                className="w-full rounded-xl bg-black/30 border border-white/10 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
              />
            </div>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={submitContactForm}
                disabled={!contactFormComplete}
                className="rounded-xl bg-stark-blue hover:bg-blue-600 disabled:opacity-40 text-white px-4 py-2 text-sm font-medium"
              >
                Submit
              </button>
            </div>
          </div>
        )}

        {/* Normal streaming — only when the contact form is not blocking the view */}
        {!shouldShowContactForm && isTyping && streamingText && (
          <MessageBubble role="assistant">{streamingText}</MessageBubble>
        )}

        {showIdlePrompt && !ended && (
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <div className="text-sm text-slate-200 font-medium">Still there?</div>
            <div className="text-xs text-slate-400 mt-1">
              If you have more questions, I’m here. Otherwise we can wrap up this conversation.
            </div>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={onIdleContinue}
                className="rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] text-slate-200 px-4 py-2 text-sm font-medium"
              >
                Continue chatting
              </button>
              <button
                type="button"
                onClick={onIdleEnd}
                className="rounded-xl bg-stark-blue hover:bg-blue-600 text-white px-4 py-2 text-sm font-medium"
              >
                End conversation
              </button>
            </div>
          </div>
        )}

        {ended && (
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-200">
            Thanks for chatting with us. This conversation has been ended.
          </div>
        )}

        {!isTyping && lastSources?.sources?.length ? (
          <div className="px-2">
            <details className="text-xs text-slate-400">
              <summary className="cursor-pointer select-none">
                Sources ({lastSources.sources.length}) — {lastSources.agent || "assistant"}
              </summary>
              <div className="mt-2 space-y-2">
                {lastSources.sources.map((s, idx) => (
                  <div
                    key={idx}
                    className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2"
                  >
                    <div className="text-slate-300">
                      {s.solution_name || s.problem_title || s.id || "match"}
                    </div>
                    <div className="text-slate-500">
                      {(s.namespace ? `${s.namespace} • ` : "")}
                      {(typeof s.score === "number" ? `score ${s.score.toFixed(2)}` : "")}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          </div>
        ) : null}
        {!shouldShowContactForm && isTyping && !streamingText && (
          <MessageBubble role="assistant">
            <TypingIndicator />
          </MessageBubble>
        )}
        {error && (
          <p className="text-red-400 text-sm px-2">{error}</p>
        )}
      </div>
      <form
        onSubmit={onSubmit}
        className="border-t border-white/10 p-4 bg-transparent"
      >
        <div className="flex items-end gap-3 rounded-2xl bg-white/[0.03] border border-white/10 px-3 py-2">
          <textarea
            className="flex-1 bg-transparent text-slate-100 text-sm px-1 py-2 focus:outline-none resize-none min-h-[44px] max-h-40 placeholder:text-slate-500"
            placeholder={sessionId ? "Message" : "Connecting…"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!sessionId || isTyping || ended || shouldShowContactForm}
            rows={1}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              if (e.shiftKey) return; // allow newline with Shift+Enter
              e.preventDefault();
              if (!input.trim() || !sessionId || isTyping || ended || shouldShowContactForm) return;
              const t = input;
              setInput("");
              lastActivityRef.current = Date.now();
              setShowIdlePrompt(false);
              void sendMessage(t);
            }}
            aria-label="Chat message"
          />
          <button
            type="submit"
            disabled={!sessionId || isTyping || !input.trim() || ended || shouldShowContactForm}
            className="rounded-xl bg-stark-blue hover:bg-blue-600 disabled:opacity-40 text-white px-4 py-2 text-sm font-medium"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
