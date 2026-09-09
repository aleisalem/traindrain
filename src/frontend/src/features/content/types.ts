export type ModuleActor = {
  id: string;
  display_name: string;
};

export type AssetKind = "image" | "attachment";

export type ModuleAsset = {
  id: string;
  kind: AssetKind;
  /** The authorizing API path — never a presigned URL. */
  url: string;
  content_type: string;
  size_bytes: number;
  original_filename: string;
  uploaded_by: ModuleActor;
  created_at: string;
  /** How many of this module's pages embed it, so a delete is an informed one. */
  referenced_by_pages: number;
};

export type ModuleAssetsBody = {
  assets: ModuleAsset[];
  total_bytes: number;
  max_module_bytes: number;
  max_image_bytes: number;
  max_attachment_bytes: number;
};

export type ModuleBody = {
  id: string;
  translation_group_id: string;
  language: string;
  title: string;
  description: string | null;
  estimated_duration_minutes: number | null;
  status: string;
  created_by: ModuleActor;
  last_edited_by: ModuleActor;
  created_at: string;
  updated_at: string;
};
