import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatWidget from "./ChatWidget.jsx";

const createSessionMock = vi.fn(async () => ({ session_id: "new-session" }));

vi.mock("../utils/api.js", () => ({
  createSession: () => createSessionMock(),
}));

vi.mock("../hooks/useChat.js", () => ({
  useChat: () => ({
    messages: [],
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
});

