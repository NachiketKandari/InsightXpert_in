import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConversationList } from "./conversation-list";
import { useChatStore } from "@/stores/chat-store";
import type { Conversation } from "@/types/chat";

function makeConvos(n: number): Conversation[] {
  const now = Date.now();
  return Array.from({ length: n }, (_, i) => ({
    id: `c${i}`,
    title: `Conversation number ${i}`,
    messages: [],
    createdAt: now - i * 1000,
    // Half "today", half older than today.
    updatedAt: i < n / 2 ? now - i * 1000 : now - 3 * 86400000 - i * 1000,
  }));
}

describe("ConversationList Phase2", () => {
  const origOffsetHeight = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "offsetHeight"
  );

  beforeEach(() => {
    // jsdom has no layout: report a 600px scroll viewport and 52px rows
    // so the virtualizer computes a realistic window.
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get() {
        const el = this as HTMLElement;
        if (el.dataset?.index !== undefined) return 52;
        if (el.getAttribute?.("role") === "list") return 600;
        return 0;
      },
    });
    useChatStore.setState({
      conversations: [],
      activeConversationId: null,
      isLoadingConversations: false,
    });
  });

  afterEach(() => {
    if (origOffsetHeight) {
      Object.defineProperty(
        HTMLElement.prototype,
        "offsetHeight",
        origOffsetHeight
      );
    }
  });

  it("virtualizes: 120 conversations render a bounded subset", () => {
    useChatStore.setState({ conversations: makeConvos(120) });
    render(<ConversationList />);
    const openButtons = screen.getAllByRole("button", {
      name: /Open conversation:/,
    });
    // Without virtualization this would be 120. Overscan keeps it small.
    expect(openButtons.length).toBeLessThan(40);
    expect(openButtons.length).toBeGreaterThan(0);
  });

  it("keeps Today/Older group headers", () => {
    useChatStore.setState({ conversations: makeConvos(10) });
    const { container } = render(<ConversationList />);
    const text = container.textContent ?? "";
    expect(text).toContain("Today");
    expect(text).toContain("Older");
  });

  it("exposes a labelled list with few tab stops", () => {
    useChatStore.setState({ conversations: makeConvos(120) });
    render(<ConversationList />);
    const list = screen.getByRole("list", { name: "Conversations" });
    expect(list).toBeInTheDocument();
    const focusable = list.querySelectorAll(
      'a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])'
    );
    expect(focusable.length).toBeLessThan(40);
  });
});
