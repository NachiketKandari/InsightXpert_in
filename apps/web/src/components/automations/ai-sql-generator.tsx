"use client";

// Phase C1: emits SQL via callback (de-coupled from the old workflow-builder store).

import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { generateSql } from "@/lib/automations/api";

interface AiSqlGeneratorProps {
  onGenerated: (sql: string, prompt: string) => void;
}

export function AiSqlGenerator({ onGenerated }: AiSqlGeneratorProps) {
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const handleGenerate = async () => {
    if (!prompt.trim() || isGenerating) return;
    setError(null);
    setIsGenerating(true);
    try {
      const result = await generateSql(prompt.trim());
      if (result?.sql) {
        onGenerated(result.sql, prompt.trim());
        setPrompt("");
      } else {
        setError("Failed to generate SQL. Try a different prompt.");
      }
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="space-y-2">
      <Textarea
        placeholder="Describe the query you need, e.g. 'total transactions by month'"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={3}
        className="text-sm resize-none"
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <Button
        size="sm"
        className="w-full"
        onClick={handleGenerate}
        disabled={!prompt.trim() || isGenerating}
      >
        {isGenerating ? (
          <>
            <Loader2 className="size-3.5 mr-1.5 animate-spin" />
            Generating...
          </>
        ) : (
          <>
            <Sparkles className="size-3.5 mr-1.5" />
            Generate SQL
          </>
        )}
      </Button>
    </div>
  );
}
