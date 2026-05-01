"use client";

import { AnswerChunk } from "./answer-chunk";
import type { AnswerGeneratedData } from "@/types/chunks";

interface AnswerGeneratedChunkProps {
  data: AnswerGeneratedData;
  /** Owning assistant message id — forwarded so footnote clicks can address
   * the data-table chunk for the same message. */
  messageId?: string;
}

/**
 * Tier-3: `answer_generated`. Reads `data.text` (the new strict envelope)
 * and delegates to the existing `AnswerChunk` markdown/section renderer so
 * styling matches the fork's analyst output.
 */
export function AnswerGeneratedChunk({ data, messageId }: AnswerGeneratedChunkProps) {
  return <AnswerChunk content={data.text ?? ""} messageId={messageId} />;
}
