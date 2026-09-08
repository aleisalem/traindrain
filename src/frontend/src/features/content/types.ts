export type ModuleActor = {
  id: string;
  display_name: string;
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
