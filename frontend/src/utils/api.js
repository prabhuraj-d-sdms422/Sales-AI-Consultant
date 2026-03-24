const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function createSession() {
  const res = await fetch(`${API}/session/create`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export function getApiBase() {
  return API;
}
