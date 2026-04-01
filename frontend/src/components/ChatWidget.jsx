import { useEffect, useRef, useState } from "react";
import { createSession } from "../utils/api.js";
import { useChat } from "../hooks/useChat.js";
import MessageBubble from "./MessageBubble.jsx";
import TypingIndicator from "./TypingIndicator.jsx";
import TokenUsagePanel from "./TokenUsagePanel.jsx";

const CHAT_SESSION_ID_KEY = "stark.chat.sessionId";
const CHAT_MESSAGES_KEY = "stark.chat.messages";

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

export default function ChatWidget() {
  const [sessionId, setSessionId] = useState(null);
  const [input, setInput] = useState("");
  const { messages, streamingText, isTyping, tokenUsage, lastSources, error, sendMessage } =
    useChat(sessionId);
  const listRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const navType = typeof window !== "undefined" ? getNavigationType() : "navigate";
      if (navType === "reload") {
        try {
          window.sessionStorage.removeItem(CHAT_SESSION_ID_KEY);
          window.sessionStorage.removeItem(CHAT_MESSAGES_KEY);
        } catch {
          // ignore
        }
      }

      try {
        const existing = window.sessionStorage.getItem(CHAT_SESSION_ID_KEY);
        if (existing) {
          if (!cancelled) setSessionId(existing);
          return;
        }
      } catch {
        // ignore
      }

      try {
        const data = await createSession();
        if (cancelled) return;
        setSessionId(data.session_id);
        try {
          window.sessionStorage.setItem(CHAT_SESSION_ID_KEY, data.session_id);
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

  useEffect(() => {
    // Keep the newest streamed token visible.
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, streamingText, isTyping]);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || !sessionId) return;
    const t = input;
    setInput("");
    await sendMessage(t);
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
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role}>
            {m.content}
          </MessageBubble>
        ))}
        {isTyping && streamingText && (
          <MessageBubble role="assistant">{streamingText}</MessageBubble>
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
        {isTyping && !streamingText && (
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
            disabled={!sessionId || isTyping}
            rows={1}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              if (e.shiftKey) return; // allow newline with Shift+Enter
              e.preventDefault();
              if (!input.trim() || !sessionId || isTyping) return;
              const t = input;
              setInput("");
              void sendMessage(t);
            }}
            aria-label="Chat message"
          />
          <button
            type="submit"
            disabled={!sessionId || isTyping || !input.trim()}
            className="rounded-xl bg-stark-blue hover:bg-blue-600 disabled:opacity-40 text-white px-4 py-2 text-sm font-medium"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
