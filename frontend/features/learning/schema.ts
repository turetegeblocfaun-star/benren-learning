import { z } from "zod";

const isoDate = z.string();

export const workspaceSchema = z.object({
  course_id: z.string(),
  action: z.object({
    type: z.enum(["upload_material", "generate_note", "generate_quiz", "generate_review_plan", "tutor", "quiz", "wrong_retry", "note_review"]),
    target_id: z.string(),
    reason: z.string(),
    duration_min: z.number().int(),
    plan_id: z.string().nullable().optional(),
  }),
  derived_by: z.enum(["workflow", "model", "fallback_rule"]),
});

export const noteSectionSchema = z.object({
  id: z.string(),
  title: z.string(),
  body: z.string(),
  provenance: z.enum(["uploaded_material", "material_example", "official_supplement", "ai_inference", "needs_review"]),
  source_ref_ids: z.array(z.string()),
});

const legacyNoteContentSchema = z.object({
  title: z.string(),
  summary: z.string(),
  sections: z.array(noteSectionSchema),
});

export const providerNoteContentSchema = z.object({
  title: z.string(),
  sections: z.array(z.object({
    heading: z.string(), summary: z.string(), concepts: z.array(z.string()), primary_source_refs: z.array(z.string()),
  })).min(1),
  material_cases: z.array(z.object({ title: z.string(), case: z.string(), learning_point: z.string(), primary_source_refs: z.array(z.string()) })).default([]),
  official_extensions: z.array(z.record(z.string(), z.unknown())).default([]),
  ai_inferences: z.array(z.record(z.string(), z.unknown())).default([]),
  common_mistakes: z.array(z.unknown()).default([]),
  uncertainties: z.array(z.record(z.string(), z.unknown())).default([]),
  feedback_overlays: z.array(z.record(z.string(), z.unknown())).optional(),
});

function recordText(value: unknown) {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return String(value ?? "");
  return Object.values(value).filter((item) => typeof item === "string").join(" · ");
}

function recordRefs(value: Record<string, unknown>) {
  for (const key of ["primary_source_refs", "official_source_refs", "source_ref_ids"]) {
    const refs = value[key];
    if (Array.isArray(refs)) return refs.filter((item): item is string => typeof item === "string");
  }
  return [];
}

export const noteContentSchema = z.union([legacyNoteContentSchema, providerNoteContentSchema]).transform((content) => {
  if ("summary" in content) return content;
  const sections = [
    ...content.sections.map((section, index) => ({ id: `course-${index}`, title: section.heading, body: `${section.summary}${section.concepts.length ? `\n核心概念：${section.concepts.join("、")}` : ""}`, provenance: "uploaded_material" as const, source_ref_ids: section.primary_source_refs })),
    ...content.material_cases.map((item, index) => ({ id: `case-${index}`, title: item.title, body: `${item.case}\n学习要点：${item.learning_point}`, provenance: "material_example" as const, source_ref_ids: item.primary_source_refs })),
    ...content.official_extensions.map((item, index) => ({ id: `official-${index}`, title: "官方补充", body: recordText(item), provenance: "official_supplement" as const, source_ref_ids: recordRefs(item) })),
    ...content.ai_inferences.map((item, index) => ({ id: `inference-${index}`, title: "AI 推断", body: recordText(item), provenance: "ai_inference" as const, source_ref_ids: recordRefs(item) })),
    ...content.common_mistakes.map((item, index) => ({ id: `mistake-${index}`, title: "常见错误", body: recordText(item), provenance: "ai_inference" as const, source_ref_ids: [] })),
    ...content.uncertainties.map((item, index) => ({ id: `uncertainty-${index}`, title: "待核对", body: recordText(item), provenance: "needs_review" as const, source_ref_ids: recordRefs(item) })),
  ];
  return { title: content.title, summary: content.sections.map((item) => item.summary).join(" "), sections };
});

const legacyGraphContentSchema = z.object({
  nodes: z.array(z.object({
    id: z.string(),
    label: z.string(),
    mastery_state: z.enum(["unassessed", "learning", "mastered", "needs_review"]),
    source_ref_ids: z.array(z.string()),
  })),
  edges: z.array(z.object({ from: z.string(), to: z.string(), label: z.string(), source_ref_ids: z.array(z.string()) })),
});

const providerGraphContentSchema = z.object({
  nodes: z.array(z.object({
    id: z.string(), layer: z.enum(["course_core", "official_extension"]), label: z.string(), definition: z.string(),
    confidence: z.enum(["high", "medium", "low"]), primary_source_refs: z.array(z.string()), official_source_refs: z.array(z.string()),
    mastery_state: z.enum(["unassessed", "needs_review", "mastered"]).default("unassessed"),
  })),
  edges: z.array(z.object({
    from: z.string(), to: z.string(), layer: z.enum(["course_core", "official_extension"]), type: z.string(),
    confidence: z.enum(["high", "medium"]), primary_source_refs: z.array(z.string()), official_source_refs: z.array(z.string()),
  })),
  proposed_edges: z.array(z.record(z.string(), z.unknown())).default([]),
  conflicts: z.array(z.record(z.string(), z.unknown())).default([]),
  feedback_overlays: z.array(z.record(z.string(), z.unknown())).optional(),
});

export const graphContentSchema = z.union([legacyGraphContentSchema, providerGraphContentSchema]).transform((content) => {
  if (content.nodes.every((node) => "source_ref_ids" in node)) return content as z.infer<typeof legacyGraphContentSchema>;
  const provider = content as z.infer<typeof providerGraphContentSchema>;
  return {
    nodes: provider.nodes.map((node) => ({ id: node.id, label: node.label, mastery_state: node.mastery_state, source_ref_ids: [...node.primary_source_refs, ...node.official_source_refs] })),
    edges: provider.edges.map((edge) => ({ from: edge.from, to: edge.to, label: edge.type, source_ref_ids: [...edge.primary_source_refs, ...edge.official_source_refs] })),
  };
});

export const learningAssetVersionSchema = z.object({
  id: z.string(),
  version_no: z.number().int(),
  source_kind: z.string(),
  content: z.record(z.string(), z.unknown()),
  source_ref_ids: z.array(z.string()),
  prompt_id: z.string(),
  prompt_version: z.string(),
  schema_version: z.string(),
  requested_model_id: z.string(),
  returned_model_id: z.string().nullable(),
  created_by: z.string(),
  created_at: isoDate,
});

export const learningAssetSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  asset_type: z.enum(["note", "graph"]),
  status: z.string(),
  context_snapshot_id: z.string(),
  parent_asset_version_id: z.string().nullable(),
  version: z.number().int(),
  error_code: z.string().nullable(),
  error_message: z.string().nullable(),
  current_version: learningAssetVersionSchema.nullable(),
  created_at: isoDate,
  updated_at: isoDate,
});

export const learningAssetTaskSchema = z.object({ asset: learningAssetSchema, task_id: z.string() });

const quizQuestionSchema = z.object({
  id: z.string(),
  version_no: z.number().int(),
  type: z.enum(["single_choice", "true_false"]),
  stem: z.string(),
  options: z.array(z.object({ id: z.string(), text: z.string() })),
  concept_ids: z.array(z.string()),
  source_ref_ids: z.array(z.string()),
  status: z.enum(["active", "withdrawn"]),
}).strict();

export const quizSchema = z.object({
  id: z.string(), course_id: z.string(), context_snapshot_id: z.string(), status: z.string(), difficulty: z.string(),
  requested_count: z.number().int(), published_count: z.number().int(), withdrawn_question_ids: z.array(z.string()),
  error_code: z.string().nullable(), error_message: z.string().nullable(), questions: z.array(quizQuestionSchema),
  created_at: isoDate, updated_at: isoDate,
});
export const quizTaskSchema = z.object({ quiz: quizSchema, task_id: z.string() });

export const quizAttemptSchema = z.object({
  id: z.string(), question_id: z.string(), selected_answer: z.string(), is_correct: z.boolean(), correct_answer: z.string(),
  explanation: z.string(), source_ref_ids: z.array(z.string()), wrongbook_entry_id: z.string().nullable(), created_at: isoDate,
});

export const wrongbookEntrySchema = z.object({
  id: z.string(), question_id: z.string(), status: z.enum(["needs_review", "resolved"]), wrong_count: z.number().int(),
  correct_after_wrong_count: z.number().int(), question_version: z.number().int(), stem: z.string(),
  history: z.array(z.record(z.string(), z.unknown())), updated_at: isoDate,
});
export const wrongbookSchema = z.array(wrongbookEntrySchema);

export const tutorTurnSchema = z.object({
  id: z.string(), ordinal: z.number().int(), status: z.string(), input_mode: z.string(), user_message: z.string(),
  retrieval_run_id: z.string().nullable(), next_state: z.string().nullable(),
  strategy: z.string().nullable(), message: z.string().nullable(), source_ref_ids: z.array(z.string()), warnings: z.array(z.string()),
  source_reference_kind: z.enum(["cited", "material_scope"]).default("material_scope"),
  error_code: z.string().nullable(), error_message: z.string().nullable(), created_at: isoDate, completed_at: isoDate.nullable(),
});

export const tutorSessionSchema = z.object({
  id: z.string(), course_id: z.string(), context_snapshot_id: z.string(), context_mode: z.enum(["direct_full", "indexed_full", "tutor_rag"]),
  learning_goal: z.string(), target_problem: z.string().nullable(), fsm_state: z.string(), status: z.string(),
  turn_count: z.number().int(), max_turns: z.number().int(), version: z.number().int(), turns: z.array(tutorTurnSchema),
  created_at: isoDate, updated_at: isoDate, ended_at: isoDate.nullable(),
});
export const tutorTurnTaskSchema = z.object({ turn: tutorTurnSchema, task_id: z.string() });

export const retrievalRunSchema = z.object({
  id: z.string(), course_id: z.string(), context_snapshot_id: z.string(), tutor_turn_id: z.string(), status: z.string(),
  raw_query: z.string(), rewritten_queries: z.array(z.string()), retrieval_config_version: z.string(), degraded_reasons: z.array(z.string()),
  evidence_count: z.number().int(), evidence: z.array(z.object({
    source_ref_id: z.string(), material_id: z.string(), material_version_id: z.string(), rank: z.number().int(), text: z.string(),
    locator: z.record(z.string(), z.unknown()), keyword_score: z.number(), vector_score: z.number(), rerank_score: z.number(),
  })), created_at: isoDate, completed_at: isoDate.nullable(),
});

export type Workspace = z.infer<typeof workspaceSchema>;
export type LearningAsset = z.infer<typeof learningAssetSchema>;
export type NoteContent = z.infer<typeof noteContentSchema>;
export type GraphContent = z.infer<typeof graphContentSchema>;
export type Quiz = z.infer<typeof quizSchema>;
export type QuizAttempt = z.infer<typeof quizAttemptSchema>;
export type WrongbookEntry = z.infer<typeof wrongbookEntrySchema>;
export type TutorSession = z.infer<typeof tutorSessionSchema>;
