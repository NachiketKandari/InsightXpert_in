"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, FileSpreadsheet, X, Loader2, Database } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useQueryClient } from "@tanstack/react-query";
import { SSE_BASE_URL } from "@/lib/constants";
import { useChatStore } from "@/stores/chat-store";
import type { DatabaseUploadResponse, UploadPreviewResponse } from "@/types/database";
import { apiFetch } from "@/lib/api";

const ACCEPTED_EXTS = [".csv", ".xlsx", ".xls"];
const ACCEPTED_EXT_DISPLAY = ".csv, .xlsx, .xls";
const ACCEPT_MIME = ".csv,.xlsx,.xls";
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB
const DB_ID_PATTERN = /^[a-z0-9][a-z0-9_\-]{0,62}$/;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function slugify(fileName: string): string {
  const base = fileName.replace(/\.(csv|xlsx|xls)$/i, "");
  return base
    .toLowerCase()
    .replace(/[^a-z0-9_\-]+/g, "_")
    .replace(/^[^a-z0-9]+/, "")
    .slice(0, 63);
}

const TYPE_BADGE_CLASS: Record<string, string> = {
  INTEGER: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  REAL: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  TEXT: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  DATETIME: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  BOOLEAN: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

export interface CsvUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploadSuccess?: (dbId: string) => void;
  /** Called when upload completes and profile_required=true — consumer should trigger profiling. */
  onProfileRequired?: (dbId: string) => void;
}

export function CsvUploadDialog({
  open,
  onOpenChange,
  onUploadSuccess,
  onProfileRequired,
}: CsvUploadDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [dbId, setDbId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<UploadPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  const setSelectedDbId = useChatStore((s) => s.setSelectedDbId);
  const queryClient = useQueryClient();

  const reset = useCallback(() => {
    setFile(null);
    setDbId("");
    setError(null);
    setUploading(false);
    setUploadProgress(0);
    setPreview(null);
    setPreviewLoading(false);
    if (xhrRef.current) {
      xhrRef.current.abort();
      xhrRef.current = null;
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) reset();
      onOpenChange(nextOpen);
    },
    [reset, onOpenChange],
  );

  // Fetch preview when file changes.
  useEffect(() => {
    if (!file || !open) return;
    let cancelled = false;

    async function loadPreview() {
      setPreviewLoading(true);
      setPreview(null);
      setError(null);
      try {
        const formData = new FormData();
        formData.append("file", file!);
        const res = await apiFetch("/api/v1/databases/upload-preview", {
          method: "POST",
          body: formData,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            typeof body?.detail === "string" ? body.detail : `Preview failed (HTTP ${res.status})`,
          );
        }
        const data = (await res.json()) as UploadPreviewResponse;
        if (!cancelled) setPreview(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to preview file.");
        }
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    }

    loadPreview();
    return () => { cancelled = true; };
  }, [file, open]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (!selected) return;

    const ext = "." + selected.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTS.includes(ext)) {
      setError(`Unsupported file type. Please upload ${ACCEPTED_EXT_DISPLAY}.`);
      return;
    }
    if (selected.size > MAX_FILE_SIZE) {
      setError(`File is too large (${formatFileSize(selected.size)}). Max ${formatFileSize(MAX_FILE_SIZE)}.`);
      return;
    }

    setFile(selected);
    setError(null);
    if (!dbId.trim()) setDbId(slugify(selected.name));
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("Please select a file.");
      return;
    }
    const trimmedId = dbId.trim();
    if (!DB_ID_PATTERN.test(trimmedId)) {
      setError(
        "Database ID must be 1-63 chars of lowercase letters, digits, underscores, or hyphens, starting with a letter or digit.",
      );
      return;
    }

    setUploading(true);
    setUploadProgress(0);
    setError(null);

    const formData = new FormData();
    formData.append("db_id", trimmedId);
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;

    xhr.upload.onprogress = (evt) => {
      if (evt.lengthComputable) {
        setUploadProgress(Math.round((evt.loaded / evt.total) * 100));
      }
    };

    xhr.onload = () => {
      xhrRef.current = null;
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText) as DatabaseUploadResponse;
          setSelectedDbId(data.db_id);
          toast.success(`Uploaded "${data.db_id}" and set as active.`);
          void queryClient.invalidateQueries({ queryKey: ["databases", "list"] });
          onUploadSuccess?.(data.db_id);
          if (data.profile_required) {
            onProfileRequired?.(data.db_id);
          }
          handleOpenChange(false);
        } catch {
          setError("Invalid response from server.");
        }
      } else {
        let msg: string;
        try {
          const body = JSON.parse(xhr.responseText);
          const detail = body?.detail;
          msg =
            typeof detail === "string"
              ? detail
              : Array.isArray(detail)
                ? detail.map((e: { msg?: string }) => e?.msg ?? JSON.stringify(e)).join("; ")
                : `Upload failed (HTTP ${xhr.status})`;
        } catch {
          msg = `Upload failed (HTTP ${xhr.status})`;
        }
        setError(msg);
        toast.error(msg);
      }
      setUploading(false);
    };

    xhr.onerror = () => {
      xhrRef.current = null;
      const msg = "Network error during upload.";
      setError(msg);
      toast.error(msg);
      setUploading(false);
    };

    xhr.onabort = () => {
      xhrRef.current = null;
      setUploading(false);
    };

    xhr.open("POST", `${SSE_BASE_URL}/api/v1/databases/upload-csv`);
    xhr.withCredentials = true;
    xhr.send(formData);
  };

  const fileExt = file ? "." + file.name.split(".").pop()?.toLowerCase() : null;
  const isExcel = fileExt === ".xlsx" || fileExt === ".xls";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm">
            <FileSpreadsheet className="size-4 text-primary dark:text-cyan-accent" />
            Upload Dataset
          </DialogTitle>
          <DialogDescription>
            Upload a CSV or Excel file — it will be converted to a queryable SQLite database.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleUpload} className="space-y-4">
          {/* File picker */}
          <div className="space-y-2">
            <Label htmlFor="csv-file" className="text-xs font-medium">
              File
            </Label>
            {!file ? (
              <div
                className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border/60 bg-muted/30 p-6 cursor-pointer hover:border-primary/40 hover:bg-muted/50 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <FileSpreadsheet className="size-8 text-muted-foreground/60" />
                <p className="text-sm text-muted-foreground">Click to select a file</p>
                <p className="text-xs text-muted-foreground/60">
                  {ACCEPTED_EXT_DISPLAY} up to {formatFileSize(MAX_FILE_SIZE)}
                </p>
              </div>
            ) : (
              <div className="flex items-center gap-3 rounded-lg border border-border/60 bg-muted/30 p-3">
                <FileSpreadsheet className="size-5 text-primary dark:text-cyan-accent shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{file.name}</p>
                  <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0"
                  onClick={() => {
                    setFile(null);
                    setPreview(null);
                    if (fileInputRef.current) fileInputRef.current.value = "";
                  }}
                  aria-label="Remove file"
                >
                  <X className="size-3.5" />
                </Button>
              </div>
            )}
            <input
              ref={fileInputRef}
              id="csv-file"
              type="file"
              accept={ACCEPT_MIME}
              className="hidden"
              onChange={handleFileChange}
            />
          </div>

          {/* Preview section */}
          {previewLoading && (
            <div className="flex items-center justify-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Analyzing file…
            </div>
          )}

          {preview && !previewLoading && (
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium">
                  Preview — {preview.row_count.toLocaleString()} row{preview.row_count !== 1 ? "s" : ""}
                </p>
                {preview.sheet_name && (
                  <span className="text-[10px] text-muted-foreground">
                    Sheet: {preview.sheet_name}
                    {preview.sheet_names && preview.sheet_names.length > 1 &&
                      ` (of ${preview.sheet_names.length})`}
                  </span>
                )}
                {preview.encoding && preview.encoding !== "utf-8" && (
                  <span className="text-[10px] text-muted-foreground">
                    Encoding: {preview.encoding}
                  </span>
                )}
              </div>

              {/* Data rows preview */}
              {preview.preview_rows.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] font-medium text-muted-foreground">Data Preview</p>
                  <div className="overflow-x-auto rounded border border-border/30">
                    <table className="w-full text-[11px]">
                      <thead>
                        <tr className="border-b border-border/40 bg-muted/30">
                          {preview.columns.slice(0, 10).map((col) => (
                            <th key={col.name} className="text-left py-1 px-2 font-medium text-muted-foreground whitespace-nowrap">
                              {col.name}
                            </th>
                          ))}
                          {preview.columns.length > 10 && (
                            <th className="text-left py-1 px-2 font-medium text-muted-foreground">
                              +{preview.columns.length - 10} more
                            </th>
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.preview_rows.map((row, i) => (
                          <tr key={i} className="border-b border-border/20 last:border-0">
                            {preview.columns.slice(0, 10).map((col) => (
                              <td key={col.name} className="py-1 px-2 whitespace-nowrap truncate max-w-[150px]">
                                {row[col.name] ?? ""}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {preview.row_count > 5 && (
                    <p className="text-[10px] text-muted-foreground">
                      Showing first 5 of {preview.row_count.toLocaleString()} rows
                    </p>
                  )}
                </div>
              )}

              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b border-border/40">
                      <th className="text-left py-1 pr-2 font-medium text-muted-foreground">Column</th>
                      <th className="text-left py-1 pr-2 font-medium text-muted-foreground">Type</th>
                      <th className="text-left py-1 font-medium text-muted-foreground">Sample Values</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.columns.slice(0, 15).map((col) => (
                      <tr key={col.name} className="border-b border-border/20 last:border-0">
                        <td className="py-1 pr-2 font-mono truncate max-w-[120px]">{col.name}</td>
                        <td className="py-1 pr-2">
                          <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${TYPE_BADGE_CLASS[col.inferred_type] || TYPE_BADGE_CLASS.TEXT}`}>
                            {col.inferred_type}
                          </span>
                        </td>
                        <td className="py-1 text-muted-foreground truncate max-w-[200px]">
                          {col.sample_values.slice(0, 3).join(", ") || <span className="italic">—</span>}
                        </td>
                      </tr>
                    ))}
                    {preview.columns.length > 15 && (
                      <tr>
                        <td colSpan={3} className="py-1 text-[10px] text-muted-foreground text-center">
                          …and {preview.columns.length - 15} more columns
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {isExcel && preview.sheet_names && preview.sheet_names.length > 1 && (
                <p className="text-[10px] text-muted-foreground">
                  This Excel file has {preview.sheet_names.length} sheets. Using the first sheet: &ldquo;{preview.sheet_name}&rdquo;.
                </p>
              )}
            </div>
          )}

          {/* db_id field */}
          <div className="space-y-2">
            <Label htmlFor="csv-db-id" className="text-xs font-medium">
              Database ID <span className="text-destructive">*</span>
            </Label>
            <Input
              id="csv-db-id"
              placeholder="e.g. my_sales_data"
              value={dbId}
              onChange={(e) => setDbId(e.target.value)}
              disabled={uploading}
              className="font-mono text-sm"
            />
            <p className="text-[11px] text-muted-foreground">
              1-63 chars: lowercase letters, digits, underscores, hyphens.
            </p>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </form>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => handleOpenChange(false)}
            disabled={uploading}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            disabled={uploading || !file || !dbId.trim() || previewLoading}
            onClick={handleUpload}
          >
            {uploading ? (
              <>
                <Loader2 className="size-3.5 animate-spin mr-1.5" />
                Uploading{uploadProgress > 0 ? ` ${uploadProgress}%` : "..."}
              </>
            ) : (
              <>
                <Upload className="size-3.5 mr-1.5" />
                Upload
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
