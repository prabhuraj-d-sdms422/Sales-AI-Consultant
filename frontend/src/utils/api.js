const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function createSession() {
  const res = await fetch(`${API}/session/create`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function endSession(sessionId) {
  if (!sessionId) return { status: "ended" };
  const res = await fetch(`${API}/session/end`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error("Failed to end session");
  return res.json();
}

export async function saveProfile(sessionId, profile) {
  if (!sessionId) throw new Error("Missing session id");
  const body = { session_id: sessionId, ...(profile || {}) };
  const res = await fetch(`${API}/session/profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to save profile");
  return res.json();
}

export async function getSessionConfig() {
  const res = await fetch(`${API}/session/config`);
  if (!res.ok) throw new Error("Failed to load session config");
  return res.json();
}

export function getApiBase() {
  return API;
}
