import { useCallback, useEffect, useRef, useState } from "react";
import { getApiBase } from "../utils/api.js";

const CHAT_MESSAGES_KEY = "stark.chat.messages";

export function useChat(sessionId) {
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
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return;
      setMessages(parsed);
    } catch {
      // ignore unreadable storage
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
        const res = await fetch(`${api}/chat/message`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, message: text.trim() }),
          signal: controller.signal,
        });
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
    [sessionId],
  );

  return { messages, streamingText, isTyping, tokenUsage, lastSources, error, sendMessage };
}
