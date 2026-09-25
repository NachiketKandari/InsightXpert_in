import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConversationItem } from "./conversation-item";

// Phase 1 verification: P0 a11y fixes for chat history rows.
describe("ConversationItem Phase1", () => {
  const conv = {
    id: "c1",
    title: "How many schools are there?",
    messages: [],
    createdAt: Date.now() - 10_000,
    updatedAt: Date.now(),
  };

  it("select action is a named button, not a div[role=button]", () => {
    const { container } = render(
      <ConversationItem conversation={conv} isActive={false} />
    );
    expect(container.querySelector("div[role=button]")).toBeNull();
    const openBtn = screen.getByRole("button", {
      name: "Open conversation: How many schools are there?",
    });
    expect(openBtn).toBeInTheDocument();
  });

  it("overflow menu trigger has an accessible name", () => {
    render(<ConversationItem conversation={conv} isActive={false} />);
    const trigger = screen.getByRole("button", {
      name: "Conversation actions for How many schools are there?",
    });
    expect(trigger).toBeInTheDocument();
  });

  it("timestamp uses readable size/contrast classes", () => {
    const { container } = render(
      <ConversationItem conversation={conv} isActive={false} />
    );
    expect(container.querySelector(".text-\\[10px\\]")).toBeNull();
    const ts = container.querySelector("span.text-xs.text-muted-foreground");
    expect(ts).not.toBeNull();
  });
});
