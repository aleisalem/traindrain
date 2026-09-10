import type { PageDocument } from "../../content/schema";

/** What the learner-side API returns. Deliberately separate from the authoring
 *  types: a learner reads a frozen version snapshot, and nothing here carries a
 *  draft, a revision token, or an author's name. */

export type CatalogEntry = {
  /** The material, not one particular text of it — the language variant is
   *  resolved when the learner opens it. */
  translation_group_id: string;
  language: string;
  title: string;
  description: string | null;
  estimated_duration_minutes: number | null;
  page_count: number;
  started: boolean;
  completed_at: string | null;
};

export type LearnerPage = {
  id: string;
  position: number;
  title: string;
  schema_version: number;
  /** A validated ProseMirror tree, rendered through the static renderer. */
  body: PageDocument;
};

export type LearnerAttachment = {
  id: string;
  /** The authorizing API path; the redirect it returns is what signs a URL. */
  url: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
};

export type ProgressState = {
  pages_viewed: string[];
  current_page_id: string | null;
  started_at: string;
  completed_at: string | null;
  completed_version_number: number | null;
  superseded_at: string | null;
};

export type LearnerModule = {
  translation_group_id: string;
  module_id: string;
  language: string;
  title: string;
  description: string | null;
  estimated_duration_minutes: number | null;
  version_number: number;
  pages: LearnerPage[];
  attachments: LearnerAttachment[];
  progress: ProgressState;
};

export type LearnerModuleSummary = {
  translation_group_id: string;
  title: string;
  language: string;
  estimated_duration_minutes: number | null;
  started_at: string;
  completed_at: string | null;
  completed_version_number: number | null;
  superseded_at: string | null;
  /** Whether it can still be opened — a module withdrawn since stays on the
   *  list, because the completion is the learner's, but reopening is not on
   *  offer. */
  available: boolean;
};
