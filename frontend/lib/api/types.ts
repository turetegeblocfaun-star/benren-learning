export type User = { id: string; status: string };

export type Course = {
  id: string;
  title_status: string;
  title: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  material_counts?: Record<string, number>;
};

export type JobSummary = {
  id: string;
  status: string;
  job_type: string;
  attempt: number;
  max_attempts: number;
  error_code: string | null;
};

export type Material = {
  id: string;
  course_id: string;
  batch_id: string;
  declared_type: "audio" | "text" | "board_image" | "handwriting_image";
  detected_type: string | null;
  display_name: string;
  detected_mime: string | null;
  byte_size: number;
  status: string;
  active_parse_version_id: string | null;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  jobs: JobSummary[];
};

export type Batch = {
  id: string;
  course_id: string;
  status: string;
  item_count: number;
  success_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
  materials: Material[];
};

export type Segment = {
  id: string;
  ordinal: number;
  text: string;
  locator_type: string;
  start_ms: number | null;
  end_ms: number | null;
  page_no: number | null;
  bbox: number[] | null;
  paragraph_no: number | null;
  confidence: number | null;
  review_required: boolean;
  review_accepted: boolean;
};

export type MaterialVersion = {
  id: string;
  material_id: string;
  version_no: number;
  source_kind: string;
  parse_status: string;
  parser: string | null;
  provider: string | null;
  model_id: string | null;
  confidence_summary: Record<string, unknown>;
  created_by: string;
  created_at: string;
  segments: Segment[];
};

export type TitleCandidate = {
  id: string;
  title: string;
  source_ref_ids: string[];
  confidence: number;
};

export type TitleCandidateResponse = {
  id: string;
  course_id: string;
  status: string;
  candidates: TitleCandidate[];
  source_ref_ids: string[];
  prompt_version: string;
  requested_model_id: string;
  returned_model_id: string | null;
  created_at: string;
};

export type ContextSnapshot = {
  id: string;
  course_id: string;
  task_type: string;
  context_mode: string;
  status: string;
  coverage_status: string;
  token_estimate: number;
  segment_count: number;
  policy_version: string;
  segment_plan: Record<string, unknown>[];
  index_status: string;
  indexed_chunk_count: number;
  embedding_provider: string;
  embedding_model_id: string;
  retrieval_config_version: string;
  materials: {
    material_id: string;
    parse_version_id: string;
    selected_order: number;
    display_name: string;
    covered_locator_range: Record<string, unknown>;
  }[];
  source_ref_ids: string[];
  created_at: string;
};

export type SourceRef = {
  id: string;
  material_id: string;
  material_version_id: string;
  display_name: string;
  material_type: string;
  text: string;
  locator_type: string;
  start_ms: number | null;
  end_ms: number | null;
  page_no: number | null;
  bbox: number[] | null;
  paragraph_no: number | null;
  confidence: number | null;
  preview_path: string;
};
