"use client";

import { AnswerChunk } from "./answer-chunk";
import type { AnswerGeneratedData } from "@/types/chunks";

interface AnswerGeneratedChunkProps {
  data: AnswerGeneratedData;
}

export function AnswerGeneratedChunk({ data }: AnswerGeneratedChunkProps) {
  return <AnswerChunk content={data.text ?? ""} />;
}
