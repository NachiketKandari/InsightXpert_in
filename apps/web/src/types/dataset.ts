export interface DatasetInfo {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  table_name: string | null;
  organization_id?: string | null;
  created_by: string | null;
}
