import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatWidget from "./ChatWidget.jsx";

const createSessionMock = vi.fn(async () => ({ session_id: "new-session" }));
const saveProfileMock = vi.fn(async () => ({ status: "saved" }));

vi.mock("../utils/api.js", () => ({
  createSession: () => createSessionMock(),
  saveProfile: (...args) => saveProfileMock(...args),
  endSession: vi.fn(async () => ({ status: "ended" })),
  getSessionConfig: vi.fn(async () => ({ inactivity_prompt_minutes: 10, inactivity_end_minutes: 20 })),
  getApiBase: () => "http://example.test",
}));

vi.mock("../hooks/useChat.js", () => ({
  useChat: () => ({
    // Include a user message so the contact form is triggered (new trigger condition)
    messages: [
      { role: "assistant", content: "hello" },
      { role: "user", content: "hi" },
    ],
    streamingText: "",
    isTyping: false,
    tokenUsage: null,
    lastSources: null,
    error: null,
    sendMessage: vi.fn(),
  }),
}));

describe("ChatWidget session behavior", () => {
  beforeEach(() => {
    sessionStorage.clear();
    createSessionMock.mockClear();
    saveProfileMock.mockClear();
    vi.restoreAllMocks();
  });

  it("clears persisted chat on reload and creates a new session", async () => {
    sessionStorage.setItem("stark.chat.sessionId", "old-session");
    sessionStorage.setItem(
      "stark.chat.messages",
      JSON.stringify([{ role: "user", content: "old" }]),
    );

    vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ type: "reload" }]);

    render(<ChatWidget />);

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledTimes(1);
    });

    expect(sessionStorage.getItem("stark.chat.sessionId")).toBe("new-session");
    expect(sessionStorage.getItem("stark.chat.messages")).toBeNull();
  });

  it("reuses existing sessionId on normal navigation and does not create a new session", async () => {
    sessionStorage.setItem("stark.chat.sessionId", "existing-session");
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ type: "navigate" }]);

    render(<ChatWidget />);

    await new Promise((r) => setTimeout(r, 0));
    expect(createSessionMock).toHaveBeenCalledTimes(0);
    expect(sessionStorage.getItem("stark.chat.sessionId")).toBe("existing-session");
  });

  it("shows required contact form after first user message with preparing-response animation, no Skip, and disables chat input", async () => {
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ type: "navigate" }]);

    render(<ChatWidget />);

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledTimes(1);
    });

    // No skip button — form is mandatory
    expect(screen.queryByRole("button", { name: /skip/i })).toBeNull();

    // "Preparing response" animation label is visible
    expect(screen.getAllByText(/preparing your response/i).length).toBeGreaterThan(0);

    // Chat input is disabled while form is open
    const [textarea] = screen.getAllByLabelText("Chat message");
    expect(textarea).toBeDisabled();
  });
});

