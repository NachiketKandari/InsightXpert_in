import { describe, it, expect } from "vitest";
import { CHUNK_TYPE_LABELS, getChunkTypeLabel } from "@/lib/chunk-labels";

describe("getChunkTypeLabel", () => {
  it("returns the mapped label for a known Tier-3 chunk type", () => {
    expect(getChunkTypeLabel("profile_loaded")).toBe("Loaded database profile");
  });

  it("covers every required Tier-3 chunk type", () => {
    expect(CHUNK_TYPE_LABELS.profile_loaded).toBe("Loaded database profile");
    expect(CHUNK_TYPE_LABELS.schema_linking_started).toBe("Linking schema");
    expect(CHUNK_TYPE_LABELS.candidate_sqls_generated).toBe("Drafted trial queries");
    expect(CHUNK_TYPE_LABELS.literals_extracted).toBe("Extracted literals");
    expect(CHUNK_TYPE_LABELS.semantic_matches).toBe("Matched columns semantically");
    expect(CHUNK_TYPE_LABELS.join_paths_added).toBe("Resolved join paths");
    expect(CHUNK_TYPE_LABELS.linked_schema_final).toBe("Linked schema ready");
    expect(CHUNK_TYPE_LABELS.sql_generated).toBe("Generated SQL");
    expect(CHUNK_TYPE_LABELS.sql_executing).toBe("Executing SQL");
    expect(CHUNK_TYPE_LABELS.rows_returned).toBe("Rows returned");
    expect(CHUNK_TYPE_LABELS.answer_generated).toBe("Generated answer");
    expect(CHUNK_TYPE_LABELS.stats_context).toBe("Retrieved dataset statistics");
    expect(CHUNK_TYPE_LABELS.tool_call).toBe("Tool call");
    expect(CHUNK_TYPE_LABELS.tool_result).toBe("Tool result");
    expect(CHUNK_TYPE_LABELS.status).toBe("Status");
    expect(CHUNK_TYPE_LABELS.metrics).toBe("Metrics");
  });

  it("title-cases unknown snake_case types instead of returning the raw string", () => {
    expect(getChunkTypeLabel("foo_bar_baz")).toBe("Foo Bar Baz");
  });

  it("title-cases a single-word unknown type", () => {
    expect(getChunkTypeLabel("mystery")).toBe("Mystery");
  });

  it("returns empty string for an empty input", () => {
    expect(getChunkTypeLabel("")).toBe("");
  });

  it("handles consecutive underscores gracefully", () => {
    expect(getChunkTypeLabel("foo__bar")).toBe("Foo Bar");
  });
});
