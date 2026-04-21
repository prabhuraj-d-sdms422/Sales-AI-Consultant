import { useCallback, useEffect, useRef, useState } from "react";
import { createSession, getApiBase, getSessionConfig } from "../utils/api.js";

const CHAT_MESSAGES_KEY = "stark.chat.messages";
const CHAT_SESSION_ID_KEY = "stark.chat.sessionId";
const CHAT_GREETING_KEY = "stark.chat.greeting";

function buildGreeting(config) {
  const consultant = (config?.consultant_name || "Stark Digital’s AI Sales Consultant").trim();
  const company = (config?.company_name || "Stark Digital").trim();
  // Option A, env-configurable
  return `Hi — I’m ${consultant}, ${company}’s AI Sales Consultant. How can I help today?`;
}

export function useChat(sessionId, setSessionId) {
  const [messages, setMessages] = useState([]);
  const [streamingText, setStreamingText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [tokenUsage, setTokenUsage] = useState(null);
  const [lastSources, setLastSources] = useState(null);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!sessionId) return;
    if (typeof window === "undefined") return;
    if (messages.length) return;
    try {
      const raw = window.sessionStorage.getItem(CHAT_MESSAGES_KEY);
      if (!raw) {
        // No messages yet: load greeting from backend config (env-driven).
        (async () => {
          try {
            const cfg = await getSessionConfig();
            const greeting = buildGreeting(cfg);
            try {
              window.sessionStorage.setItem(CHAT_GREETING_KEY, greeting);
            } catch {
              // ignore storage failures
            }
            setMessages([{ role: "assistant", content: greeting }]);
          } catch {
            const fallback = "Hi — I’m Stark Digital’s AI Sales Consultant. How can I help today?";
            setMessages([{ role: "assistant", content: fallback }]);
          }
        })();
        return;
      }
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return;
      setMessages(parsed);
    } catch {
      // If storage is unreadable (corrupt/quota), fall back to a clean greeting.
      const fallback = "Hi — I’m Stark Digital’s AI Sales Consultant. How can I help today?";
      setMessages([{ role: "assistant", content: fallback }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(CHAT_MESSAGES_KEY, JSON.stringify(messages));
    } catch {
      // ignore quota / privacy mode failures
    }
  }, [sessionId, messages]);

  const sendMessage = useCallback(
    async (text) => {
      if (!sessionId || !text.trim()) return;
      setError(null);
      const userMsg = { role: "user", content: text.trim() };
      setMessages((m) => [...m, userMsg]);
      setIsTyping(true);
      setStreamingText("");

      const api = getApiBase();
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const doFetch = async (sid) =>
          fetch(`${api}/chat/message`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sid, message: text.trim() }),
            signal: controller.signal,
          });

        let res = await doFetch(sessionId);
        if ((res.status === 404 || res.status === 409) && typeof setSessionId === "function") {
          // Session expired (Redis TTL) — create a new one and retry once.
          const data = await createSession();
          const newId = data?.session_id;
          if (newId) {
            try {
              window.sessionStorage.setItem(CHAT_SESSION_ID_KEY, newId);
            } catch {
              // ignore storage failures
            }
            setSessionId(newId);
            res = await doFetch(newId);
          }
        }
        if (!res.ok) throw new Error(`Chat error: ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let assistant = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const block of parts) {
            const line = block.trim();
            if (!line.startsWith("data:")) continue;
            const payload = JSON.parse(line.replace(/^data:\s*/, ""));
            if (payload.type === "token" && payload.token) {
              assistant += payload.token;
              setStreamingText(assistant);
            }
            if (payload.type === "usage") {
              setTokenUsage(payload);
            }
            if (payload.type === "sources") {
              setLastSources(payload);
            }
            if (payload.type === "error") {
              throw new Error(payload.message || "Stream error");
            }
          }
        }
        setMessages((m) => [...m, { role: "assistant", content: assistant }]);
        setStreamingText("");
      } catch (e) {
        if (e.name === "AbortError") return;
        setError(e.message || "Something went wrong");
      } finally {
        setIsTyping(false);
        abortRef.current = null;
      }
    },
    [sessionId, setSessionId],
  );

  return { messages, streamingText, isTyping, tokenUsage, lastSources, error, sendMessage };
}
