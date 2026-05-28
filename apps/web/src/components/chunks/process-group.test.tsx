import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { ProcessGroup } from "./process-group";
import type { ChatChunk } from "@/types/chat";

describe("ProcessGroup component", () => {
  it("renders collapsed by default and shows correct title and step count", () => {
    const chunks = [
      {
        chunk: {
          type: "status" as const,
          data: { message: "Doing some research" },
          conversation_id: "c1",
          timestamp: 0,
        } as ChatChunk,
        index: 0,
      },
      {
        chunk: {
          type: "schema_linking_started" as const,
          data: { db_id: "test_db", question: "how many?" },
          conversation_id: "c1",
          timestamp: 1,
        } as ChatChunk,
        index: 1,
      },
    ];

    const { getByText, queryByText } = render(
      <ProcessGroup
        chunks={chunks}
        isStreaming={false}
        isLastAssistant={false}
      />
    );

    // Title is determined dynamically by types present. Schema linking is present, and streaming is false
    expect(getByText("Analyzed database schema")).toBeInTheDocument();
    expect(getByText("2 steps")).toBeInTheDocument();
    expect(getByText("Show details")).toBeInTheDocument();

    // Inside is collapsed by default, but it's in the DOM. Let's click the trigger button to toggle
    const button = getByText("Analyzed database schema").closest("button");
    expect(button).toBeInTheDocument();

    if (button) {
      fireEvent.click(button);
    }

    // Now it should show "Hide details"
    expect(getByText("Hide details")).toBeInTheDocument();
    // It should render inner chunk content (schema linking starts)
    expect(getByText(/Linking schema for/i)).toBeInTheDocument();
  });

  it("shows active title with spinner when active", () => {
    const chunks = [
      {
        chunk: {
          type: "schema_linking_started" as const,
          data: { db_id: "test_db", question: "how many?" },
          conversation_id: "c1",
          timestamp: 1,
        } as ChatChunk,
        index: 0,
      },
    ];

    const { getByText } = render(
      <ProcessGroup
        chunks={chunks}
        isStreaming={true}
        isLastAssistant={true}
      />
    );

    // Since isStreaming is true and it's last assistant, it is active
    expect(getByText("Analyzing database schema...")).toBeInTheDocument();
  });

  it("shows 'Executing SQL query' title for sql_executing chunks", () => {
    const chunks = [
      {
        chunk: {
          type: "sql_executing" as const,
          data: { sql: "SELECT * FROM users" },
          conversation_id: "c1",
          timestamp: 1,
        } as ChatChunk,
        index: 0,
      },
    ];

    const { getByText } = render(
      <ProcessGroup
        chunks={chunks}
        isStreaming={false}
        isLastAssistant={false}
      />
    );

    expect(getByText("SQL query executed")).toBeInTheDocument();
  });

  it("shows 'Executing SQL query...' title while streaming sql_executing", () => {
    const chunks = [
      {
        chunk: {
          type: "sql_executing" as const,
          data: { sql: "SELECT * FROM users" },
          conversation_id: "c1",
          timestamp: 1,
        } as ChatChunk,
        index: 0,
      },
    ];

    const { getByText } = render(
      <ProcessGroup
        chunks={chunks}
        isStreaming={true}
        isLastAssistant={true}
      />
    );

    expect(getByText("Executing SQL query...")).toBeInTheDocument();
  });
});
