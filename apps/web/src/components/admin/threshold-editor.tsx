"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Settings2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAdminThreshold, useUpdateAdminThreshold } from "@/hooks/use-admin-threshold";

export function ThresholdEditor() {
  const { data: threshold, isLoading } = useAdminThreshold();
  const updateThreshold = useUpdateAdminThreshold();
  const [value, setValue] = useState<string>("");

  useEffect(() => {
    if (threshold !== undefined) {
      setValue(threshold.toString());
    }
  }, [threshold]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseInt(value, 10);
    if (isNaN(num) || num < 0) {
      toast.error("Please enter a valid non-negative number.");
      return;
    }
    try {
      await updateThreshold.mutateAsync(num);
      toast.success("Column threshold updated successfully.");
    } catch (err) {
      toast.error("Failed to update column threshold.");
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Loading settings...</span>
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="space-y-4">
      <div className="flex items-start gap-3">
        <Settings2 className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
        <div className="flex-1 space-y-1">
          <Label htmlFor="threshold-input" className="text-sm font-medium leading-none">
            Schema Linking Column Threshold
          </Label>
          <p className="text-xs text-muted-foreground max-w-xl">
            Bypasses the full schema-linking (candidate SQL generation, LSH literal matching, semantic top-k, and join paths) and final SQL generation stages for databases with fewer columns than this number. This saves cost and improves response times for small schemas.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3 pl-8">
        <div className="w-32">
          <Input
            id="threshold-input"
            type="number"
            min="0"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="h-9"
          />
        </div>
        <Button type="submit" size="sm" disabled={updateThreshold.isPending}>
          {updateThreshold.isPending && (
            <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
          )}
          Save
        </Button>
      </div>
    </form>
  );
}
