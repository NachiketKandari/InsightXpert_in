"use client";

import { useState, useRef, useCallback } from "react";
import { Upload, FileSpreadsheet, X, Loader2, CheckCircle2 } from "lucide-react";
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
import { SSE_BASE_URL } from "@/lib/constants";
import { useChatStore } from "@/stores/chat-store";
import type { DatabaseUploadResponse } from "@/types/database";

/**
 * CsvUploadDialog — upload a `.csv` file; the backend converts it to a
 * single-table SQLite and registers it as a private database.
 *
 * Hits `POST /api/v1/databases/upload-csv` (multipart; `db_id` + `file`).
 * Response shape: `{db_id: string, source: "uploaded"}` — identical to the
 * SQLite upload route. Error/toast patterns mirror SqliteUploadDialog.
 */
interface CsvUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the new db_id string after a successful upload. */
  onUploadSuccess?: (dbId: string) => void;
}

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB — matches backend max_upload_mb default
const DB_ID_PATTERN = /^[a-z0-9][a-z0-9_\-]{0,62}$/;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Derive a lowercase-slug `db_id` from a CSV filename. */
function slugify(fileName: string): string {
  const base = fileName.replace(/\.csv$/i, "");
  return base
    .toLowerCase()
    .replace(/[^a-z0-9_\-]+/g, "_")
    .replace(/^[^a-z0-9]+/, "")
    .slice(0, 63);
}

export function CsvUploadDialog({ open, onOpenChange, onUploadSuccess }: CsvUploadDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [dbId, setDbId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  const setSelectedDbId = useChatStore((s) => s.setSelectedDbId);

  const reset = useCallback(() => {
    setFile(null);
    setDbId("");
    setError(null);
    setUploading(false);
    setUploadProgress(0);
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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (!selected) return;

    if (!selected.name.toLowerCase().endsWith(".csv")) {
      setError("Please select a .csv file.");
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
      setError("Please select a CSV file.");
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

    // Use XHR for upload progress. Send directly to SSE_BASE_URL to bypass
    // Next.js proxy body-size limits. Auth is cookie-based.
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
          toast.success(`Uploaded "${data.db_id}" as SQLite database and set as active.`);
          window.dispatchEvent(new CustomEvent("databases-changed", { detail: data }));
          onUploadSuccess?.(data.db_id);
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

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm">
            <FileSpreadsheet className="size-4 text-primary dark:text-cyan-accent" />
            Upload CSV Dataset
          </DialogTitle>
          <DialogDescription>
            Upload a CSV file — it will be converted to a queryable SQLite database.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleUpload} className="space-y-4">
          {/* File picker */}
          <div className="space-y-2">
            <Label htmlFor="csv-file" className="text-xs font-medium">
              CSV File
            </Label>
            {!file ? (
              <div
                className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border/60 bg-muted/30 p-6 cursor-pointer hover:border-primary/40 hover:bg-muted/50 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <FileSpreadsheet className="size-8 text-muted-foreground/60" />
                <p className="text-sm text-muted-foreground">Click to select a CSV file</p>
                <p className="text-xs text-muted-foreground/60">
                  .csv up to {formatFileSize(MAX_FILE_SIZE)}
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
              accept=".csv"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>

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
            disabled={uploading || !file || !dbId.trim()}
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
        {/* CheckCircle2 kept for potential success state; hidden by default. */}
        <CheckCircle2 className="hidden" />
      </DialogContent>
    </Dialog>
  );
}
