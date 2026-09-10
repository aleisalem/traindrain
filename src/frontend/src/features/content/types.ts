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
  /** How many of this module's draft pages reference it, so a delete is an informed one. */
  referenced_by_pages: number;
  /** How many published versions reference it — the heavier warning, since a
   *  snapshot is immutable and cannot be edited to remove the reference. */
  referenced_by_versions: number;
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
  /** Whether learners can find it in the open catalog. Separate from publishing:
   *  a module can be live without being on offer to everybody. */
  catalog_visible: boolean;
  /** The version learners are reading; `null` until the first publish. */
  current_version_number: number | null;
  created_by: ModuleActor;
  last_edited_by: ModuleActor;
  created_at: string;
  updated_at: string;
};

/** Is this a typo fix, or does everyone have to read the module again? */
export type RevisionKind = "minor" | "substantive";

export type ModuleVersion = {
  id: string;
  version_number: number;
  revision_kind: RevisionKind;
  published_at: string;
  published_by: ModuleActor;
  /** The title as it stood at publish time, not as it reads today. */
  title: string;
  page_count: number;
};
