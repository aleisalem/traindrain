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
  /** The tombstone's own memory of its last version, set once when the
   *  module is deleted; `null` otherwise. */
  deleted_version_number: number | null;
  /** Free-text labels for search and filtering, sorted. */
  tags: string[];
  created_by: ModuleActor;
  last_edited_by: ModuleActor;
  created_at: string;
  updated_at: string;
};

/** Is this a typo fix, or does everyone have to read the module again? */
export type RevisionKind = "minor" | "substantive";

/** How many people the "everyone" in that question actually is.
 *  Read while the author is still choosing, so the choice is made with the
 *  number in front of them rather than after the fact. */
export type RevisionImpact = {
  completed_learners: number;
  in_progress_learners: number;
};

/** How many completion records a delete's tombstone would carry. Read while
 *  the author is still deciding, the same shape as `RevisionImpact`. */
export type DeletionImpact = {
  completion_count: number;
};

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

/** One body of material: every language it exists in, and which is primary —
 *  the variant a learner whose own language has none of the others gets. */
export type TranslationGroupBody = {
  id: string;
  primary_module_id: string | null;
  variants: ModuleBody[];
};

/** A group as far as a Content Manager may see one: a name, a description,
 *  and how many people are in it — never who they are. */
export type ContentGroup = {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
};

export type AssignmentTargetType = "user" | "group";
export type Requirement = "mandatory" | "recommended";

/** Who an assignment names. `name` is `null` for a "user" target the caller
 *  may not identify — a Content Manager, reading someone else's assignment to
 *  an individual. */
export type AssignmentTarget = {
  type: AssignmentTargetType;
  id: string;
  name: string | null;
};

export type Assignment = {
  id: string;
  translation_group_id: string;
  target: AssignmentTarget;
  due_date: string | null;
  requirement: Requirement;
  auto_reminders: boolean;
  assigned_by: ModuleActor;
  created_at: string;
};

/** Where one targeted learner stands. A completed learner whose completion was
 *  superseded by a substantive republish reports as `in_progress`, never
 *  `completed` — see `completed_at` below, which stays set regardless. */
export type LearnerState = "completed" | "in_progress" | "not_started";

/** One targeted group's material, aggregated — a Content Manager's view, so
 *  no member is ever named here. `overdue` overlaps `in_progress`/`not_started`
 *  rather than being a fourth exclusive bucket. */
export type ModuleReportGroupSummary = {
  group_id: string;
  group_name: string;
  member_count: number;
  completed: number;
  in_progress: number;
  not_started: number;
  overdue: number;
};

export type ContentManagerModuleReport = {
  translation_group_id: string;
  groups: ModuleReportGroupSummary[];
};

/** One targeted learner, as far as an Administrator may see one. */
export type ModuleReportLearner = {
  user_id: string;
  name: string;
  email: string;
  state: LearnerState;
  overdue: boolean;
  due_date: string | null;
  completed_at: string | null;
  completed_version_number: number | null;
};

export type AdministratorModuleReport = {
  translation_group_id: string;
  learners: ModuleReportLearner[];
};

/** `GET /api/content/modules/{id}/report`'s response shape differs by the
 *  caller's role on the server — never a client-side choice. `"groups"` only
 *  appears on the Content Manager shape, so it doubles as the discriminant. */
export type ModuleReport = ContentManagerModuleReport | AdministratorModuleReport;

/** One thing the converter dropped or altered while turning an uploaded
 *  document into pages — conversion is lossy by nature, so this is how the
 *  author finds out where to look. `message` is a complete, server-written
 *  sentence (English only — it often names a specific file or count) rather
 *  than something this UI re-renders per locale. */
export type ConversionReportEntry = {
  code: string;
  message: string;
};

export type DocumentImportResponse = {
  module: ModuleBody;
  conversion_report: ConversionReportEntry[];
};
