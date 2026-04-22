/**
 * Contract mirrors for the `databases` route family.
 *
 * Source of truth: `apps/api/src/insightxpert_api/routes/databases.py`.
 * Keep in sync when the Pydantic models change.
 */

export interface DatabaseListItem {
  /** Stable short identifier, e.g. `california_schools` or a user upload slug. */
  db_id: string;
  /** "bundled" | "uploaded" — lowercased origin tag. */
  source: string;
}

export interface DatabaseUploadResponse {
  db_id: string;
  source: string;
}
