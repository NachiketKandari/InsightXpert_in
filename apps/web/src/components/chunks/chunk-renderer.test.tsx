import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { ChunkRenderer } from "./chunk-renderer";
import type { ChatChunk } from "@/types/chat";

describe("ChunkRenderer status branch", () => {
  it("renders nothing for a status chunk with empty data.message and no ragContext", () => {
    const chunk: ChatChunk = {
      type: "status",
      data: { message: "" },
      conversation_id: "c1",
      timestamp: 0,
    };
    const { container } = render(<ChunkRenderer chunk={chunk} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a status chunk with whitespace-only message and no ragContext", () => {
    const chunk: ChatChunk = {
      type: "status",
      data: { message: "   " },
      conversation_id: "c1",
      timestamp: 0,
    };
    const { container } = render(<ChunkRenderer chunk={chunk} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a status chunk with no data and no content at all", () => {
    const chunk: ChatChunk = {
      type: "status",
      conversation_id: "c1",
      timestamp: 0,
    };
    const { container } = render(<ChunkRenderer chunk={chunk} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("still renders a status chunk when ragContext is present even with empty message", () => {
    const chunk: ChatChunk = {
      type: "status",
      data: { message: "", rag_context: ["doc1.md"] },
      conversation_id: "c1",
      timestamp: 0,
    };
    const { container } = render(<ChunkRenderer chunk={chunk} />);
    expect(container).not.toBeEmptyDOMElement();
  });

  it("renders a status chunk when message has content", () => {
    const chunk: ChatChunk = {
      type: "status",
      data: { message: "Linking schema" },
      conversation_id: "c1",
      timestamp: 0,
    };
    const { getByText } = render(<ChunkRenderer chunk={chunk} />);
    expect(getByText("Linking schema")).toBeInTheDocument();
  });
});
