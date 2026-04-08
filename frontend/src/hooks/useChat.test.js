import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChat } from "./useChat.js";

vi.mock("../utils/api.js", () => ({
  getApiBase: () => "http://example.test",
}));

function mockFetchDoneOk() {
  return vi.fn(async () => ({
    ok: true,
    body: {
      getReader() {
        return {
          async read() {
            return { done: true, value: undefined };
          },
        };
      },
    },
  }));
}

describe("useChat sessionStorage persistence", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("restores messages from sessionStorage once sessionId exists", async () => {
    sessionStorage.setItem(
      "stark.chat.messages",
      JSON.stringify([{ role: "user", content: "hello" }]),
    );

    const { result } = renderHook(() => useChat("session-1"));

    await waitFor(() => {
      expect(result.current.messages).toEqual([{ role: "user", content: "hello" }]);
    });
  });

  it("saves messages to sessionStorage after sending", async () => {
    globalThis.fetch = mockFetchDoneOk();

    const { result } = renderHook(() => useChat("session-1"));

    await result.current.sendMessage("Hi");

    await waitFor(() => {
      const stored = JSON.parse(sessionStorage.getItem("stark.chat.messages") || "null");
      expect(stored).toEqual([
        { role: "assistant", content: "Hi — I’m Stark Digital’s AI Sales Consultant. How can I help today?" },
        { role: "user", content: "Hi" },
        { role: "assistant", content: "" },
      ]);
    });
  });
});

