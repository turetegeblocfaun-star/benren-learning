import { delay, http, HttpResponse } from "msw";
import { z } from "zod";

const COURSE_ID = "demo-course-f3";
const fixedNow = "2026-08-31T13:20:00+08:00";

type NoteContent = {
  title: string;
  summary: string;
  sections: { id: string; title: string; body: string; provenance: string; source_ref_ids: string[] }[];
};

type Turn = {
  id: string; ordinal: number; status: string; input_mode: string; user_message: string;
  retrieval_run_id: string | null; next_state: string | null; strategy: string | null; message: string | null;
  source_ref_ids: string[]; warnings: string[]; error_code: string | null; error_message: string | null;
  created_at: string; completed_at: string | null;
};

const sourceIds = ["source-f3-chain", "source-f3-example", "source-f3-limit"];

function baseNoteContent(): NoteContent {
  return {
    title: "链式法则：从复合关系到逐层求导",
    summary: "先识别外层与内层函数，再把外层导数、内层导数和来源依据串成一条可检查的推导链。",
    sections: [
      { id: "note-core", title: "核心概念", body: "复合函数的变化来自外层函数与内层函数两层变化率的共同作用。", provenance: "uploaded_material", source_ref_ids: ["source-f3-chain"] },
      { id: "note-example", title: "课堂案例", body: "若 y=(3x+1)²，先对平方求导，再乘以内层 3。", provenance: "material_example", source_ref_ids: ["source-f3-example"] },
      { id: "note-official", title: "官方补充", body: "Leibniz 记号能把 dy/du 与 du/dx 的层级关系写得更清楚。", provenance: "official_supplement", source_ref_ids: [] },
      { id: "note-inference", title: "AI 推断", body: "容易出错的地方不是公式本身，而是漏掉内层函数的导数。", provenance: "ai_inference", source_ref_ids: ["source-f3-example"] },
      { id: "note-check", title: "待核对", body: "课堂录音中关于多层复合的第三步表述需要回听确认。", provenance: "needs_review", source_ref_ids: ["source-f3-limit"] },
    ],
  };
}

function createState() {
  const noteContent = baseNoteContent();
  return {
    noteVersion: 1,
    noteContent,
    graphStale: false,
    questionWithdrawn: false,
    attempts: [] as { selected_answer: string; is_correct: boolean; created_at: string }[],
    wrongbook: null as null | { status: "needs_review" | "resolved"; wrong_count: number; correct_after_wrong_count: number },
    sessions: {
      "tutor-rag-f3": { mode: "tutor_rag" as const, turns: [] as Turn[], getCount: 0 },
      "tutor-direct-f3": { mode: "direct_full" as const, turns: [] as Turn[], getCount: 0 },
    },
    sequence: 0,
  };
}

let state = createState();

export function resetF3MockState() {
  state = createState();
}

function nextId(prefix: string) {
  state.sequence += 1;
  return `${prefix}-f3-${state.sequence}`;
}

function error(code: string, message: string, status = 400) {
  return HttpResponse.json({ error: { code, message, request_id: `mock-f3-${code.toLowerCase()}` } }, { status });
}

function noteAsset() {
  return {
    id: "note-f3", course_id: COURSE_ID, asset_type: "note", status: "ready", context_snapshot_id: "snapshot-note-f3",
    parent_asset_version_id: null, version: state.noteVersion, error_code: null, error_message: null,
    current_version: {
      id: `note-version-f3-v${state.noteVersion}`, version_no: state.noteVersion, source_kind: state.noteVersion === 1 ? "model_generation" : "user_edit",
      content: state.noteContent, source_ref_ids: sourceIds, prompt_id: "BL-NOTE-001", prompt_version: "v2.8.0", schema_version: "note-v1",
      requested_model_id: "deepseek-chat", returned_model_id: "contract-mock-f3", created_by: state.noteVersion === 1 ? "workflow" : "user", created_at: fixedNow,
    }, created_at: fixedNow, updated_at: fixedNow,
  };
}

function graphAsset() {
  return {
    id: "graph-f3", course_id: COURSE_ID, asset_type: "graph", status: state.graphStale ? "stale" : "ready", context_snapshot_id: "snapshot-graph-f3",
    parent_asset_version_id: `note-version-f3-v${Math.max(1, state.noteVersion - (state.graphStale ? 1 : 0))}`, version: 1,
    error_code: null, error_message: null,
    current_version: {
      id: "graph-version-f3-v1", version_no: 1, source_kind: "model_generation",
      content: {
        nodes: [
          { id: "concept-composite", label: "复合函数", mastery_state: "learning", source_ref_ids: ["source-f3-chain"] },
          { id: "concept-outer", label: "外层导数", mastery_state: "unassessed", source_ref_ids: ["source-f3-example"] },
          { id: "concept-inner", label: "内层导数", mastery_state: "needs_review", source_ref_ids: ["source-f3-example"] },
          { id: "concept-limit", label: "极限", mastery_state: "mastered", source_ref_ids: ["source-f3-limit"] },
        ],
        edges: [
          { from: "concept-composite", to: "concept-outer", label: "拆分为", source_ref_ids: ["source-f3-chain"] },
          { from: "concept-outer", to: "concept-inner", label: "乘以内层变化率", source_ref_ids: ["source-f3-example"] },
          { from: "concept-limit", to: "concept-composite", label: "支撑导数定义", source_ref_ids: ["source-f3-limit"] },
        ],
      }, source_ref_ids: sourceIds, prompt_id: "BL-GRAPH-001", prompt_version: "v2.8.0", schema_version: "graph-v1",
      requested_model_id: "deepseek-chat", returned_model_id: "contract-mock-f3", created_by: "workflow", created_at: fixedNow,
    }, created_at: fixedNow, updated_at: fixedNow,
  };
}

function quizResponse() {
  const primaryStatus = state.questionWithdrawn ? "withdrawn" : "active";
  return {
    id: "quiz-f3", course_id: COURSE_ID, context_snapshot_id: "snapshot-quiz-f3", status: "ready", difficulty: "medium",
    requested_count: 2, published_count: state.questionWithdrawn ? 0 : 1,
    withdrawn_question_ids: ["question-withdrawn-f3", ...(state.questionWithdrawn ? ["question-chain-f3"] : [])],
    error_code: null, error_message: null,
    questions: [
      { id: "question-chain-f3", version_no: 1, type: "single_choice", stem: "对 y=(3x+1)² 求导，哪一步体现了链式法则？", options: [
        { id: "A", text: "2(3x+1) 再乘以内层导数 3" }, { id: "B", text: "只写成 2(3x+1)" }, { id: "C", text: "把 3x+1 当作常数" },
      ], concept_ids: ["concept-composite", "concept-inner"], source_ref_ids: ["source-f3-example"], status: primaryStatus },
      { id: "question-withdrawn-f3", version_no: 2, type: "true_false", stem: "已撤回示例题", options: [], concept_ids: [], source_ref_ids: [], status: "withdrawn" },
    ], created_at: fixedNow, updated_at: fixedNow,
  };
}

function sessionResponse(id: "tutor-rag-f3" | "tutor-direct-f3") {
  const session = state.sessions[id];
  return {
    id, course_id: COURSE_ID, context_snapshot_id: id === "tutor-rag-f3" ? "snapshot-tutor-rag-f3" : "snapshot-tutor-direct-f3",
    context_mode: session.mode, learning_goal: "真正理解链式法则，不靠背答案", target_problem: "解释为什么还要乘以内层导数",
    fsm_state: "diagnose", status: "active", turn_count: session.turns.length, max_turns: 8, version: 1, turns: session.turns,
    created_at: fixedNow, updated_at: fixedNow, ended_at: null,
  };
}

export const f3Handlers = [
  http.post("/api/v1/auth/invite-session", async ({ request }) => {
    const body = z.object({ invite_code: z.string() }).safeParse(await request.clone().json());
    if (!body.success || body.data.invite_code !== "F3-DEMO-2026") return;
    resetF3MockState();
    return HttpResponse.json({ user: { id: "demo-user-f3", status: "active" }, expires_at: fixedNow });
  }),

  http.get(`/api/v1/courses/${COURSE_ID}/workspace`, async () => {
    await delay(120);
    return HttpResponse.json({ course_id: COURSE_ID, action: { type: "generate_note", target_id: "snapshot-note-f3", reason: "材料已经可用，先整理为带来源的结构化笔记，再进入检验。", duration_min: 12, plan_id: null }, derived_by: "workflow" });
  }),

  http.post(`/api/v1/courses/${COURSE_ID}/learning-assets/notes`, async ({ request }) => {
    await delay(220);
    const body = z.object({ context_snapshot_id: z.string(), official_search_run_id: z.string().nullable().optional(), locale: z.string().optional() }).parse(await request.json());
    if (!body.context_snapshot_id.startsWith("snapshot-note")) return error("CONTEXT_TASK_MISMATCH", "这个上下文不是笔记任务。", 409);
    return HttpResponse.json({ asset: noteAsset(), task_id: "task-note-f3" }, { status: 202 });
  }),

  http.get("/api/v1/learning-assets/note-f3", async () => { await delay(100); return HttpResponse.json(noteAsset()); }),
  http.patch("/api/v1/learning-assets/note-f3", async ({ request }) => {
    await delay(160);
    const body = z.object({ content: z.record(z.string(), z.unknown()) }).parse(await request.json());
    const parsed = z.object({ title: z.string(), summary: z.string(), sections: z.array(z.object({ id: z.string(), title: z.string(), body: z.string(), provenance: z.string(), source_ref_ids: z.array(z.string()) })) }).safeParse(body.content);
    if (!parsed.success) return error("INVALID_ASSET_CONTENT", "笔记结构不完整。", 422);
    state.noteVersion += 1;
    state.noteContent = parsed.data;
    state.graphStale = true;
    return HttpResponse.json(noteAsset());
  }),

  http.post(`/api/v1/courses/${COURSE_ID}/learning-assets/graphs`, async ({ request }) => {
    await delay(220);
    const body = z.object({ context_snapshot_id: z.string(), note_version_id: z.string(), official_search_run_id: z.string().nullable().optional(), max_nodes: z.number().optional(), max_edges: z.number().optional() }).parse(await request.json());
    if (!body.note_version_id.startsWith("note-version-f3")) return error("VERSION_CONFLICT", "笔记版本已经变化，请刷新。", 409);
    state.graphStale = false;
    return HttpResponse.json({ asset: graphAsset(), task_id: "task-graph-f3" }, { status: 202 });
  }),
  http.get("/api/v1/learning-assets/graph-f3", async () => { await delay(100); return HttpResponse.json(graphAsset()); }),

  http.post(`/api/v1/courses/${COURSE_ID}/quizzes`, async () => { await delay(180); return HttpResponse.json({ quiz: quizResponse(), task_id: "task-quiz-f3" }, { status: 202 }); }),
  http.get("/api/v1/quizzes/quiz-f3", async () => { await delay(90); return HttpResponse.json(quizResponse()); }),
  http.post("/api/v1/quiz-questions/question-chain-f3/attempts", async ({ request }) => {
    await delay(150);
    if (state.questionWithdrawn) return error("QUESTION_WITHDRAWN", "题目已撤回，不再计入掌握或错题。", 409);
    const body = z.object({ selected_answer: z.string() }).parse(await request.json());
    const isCorrect = body.selected_answer === "A";
    state.attempts.push({ selected_answer: body.selected_answer, is_correct: isCorrect, created_at: fixedNow });
    if (!isCorrect) state.wrongbook = { status: "needs_review", wrong_count: 1, correct_after_wrong_count: 0 };
    if (isCorrect && state.wrongbook) {
      state.wrongbook = { ...state.wrongbook, status: "resolved", correct_after_wrong_count: 1 };
      state.questionWithdrawn = true;
    }
    return HttpResponse.json({
      id: nextId("attempt"), question_id: "question-chain-f3", selected_answer: body.selected_answer, is_correct: isCorrect,
      correct_answer: "A", explanation: "外层平方求导后，还要乘以内层 3；判分由代码按答案键确定。",
      source_ref_ids: ["source-f3-example"], wrongbook_entry_id: isCorrect ? null : "wrongbook-f3", created_at: fixedNow,
    }, { status: 201 });
  }),
  http.get(`/api/v1/courses/${COURSE_ID}/wrongbook`, async () => {
    await delay(90);
    if (!state.wrongbook) return HttpResponse.json([]);
    return HttpResponse.json([{
      id: "wrongbook-f3", question_id: "question-chain-f3", ...state.wrongbook, question_version: 1,
      stem: "对 y=(3x+1)² 求导，哪一步体现了链式法则？",
      history: state.attempts.map((attempt, index) => ({ attempt_no: index + 1, selected_answer: attempt.selected_answer, is_correct: attempt.is_correct, created_at: attempt.created_at })),
      updated_at: fixedNow,
    }]);
  }),

  http.get(/\/api\/v1\/tutor-sessions\/(tutor-rag-f3|tutor-direct-f3)$/, async ({ params }) => {
    await delay(80);
    const id = String(params["0"] ?? "") as "tutor-rag-f3" | "tutor-direct-f3";
    const session = state.sessions[id];
    if (!session) return error("NOT_FOUND", "Tutor 会话不存在。", 404);
    session.getCount += 1;
    const active = session.turns.at(-1);
    if (active?.status === "running" && session.getCount % 2 === 0) {
      const noHit = active.user_message.includes("奥赛罗") || active.user_message.includes("莎士比亚");
      active.status = noHit ? "insufficient_context" : "completed";
      active.next_state = noHit ? "recover_context" : "diagnose";
      active.message = noHit ? "所选材料没有这部分内容。你想换成链式法则的问题，还是返回增选材料？" : active.user_message.includes("答案") ? "先不直接给答案：外层变化完成后，内层变量还发生了什么变化？" : "你已经找到外层平方。下一步只看括号内部：3x+1 对 x 的变化率是多少？";
      active.source_ref_ids = noHit ? [] : ["source-f3-example"];
      active.warnings = noHit ? ["检索无命中；没有使用模型记忆补答案。"] : active.user_message.includes("答案") ? ["已阻断直接泄露目标答案，改为最小提示。"] : [];
      active.completed_at = fixedNow;
    }
    return HttpResponse.json(sessionResponse(id));
  }),
  http.post(/\/api\/v1\/tutor-sessions\/(tutor-rag-f3|tutor-direct-f3)\/turns$/, async ({ params, request }) => {
    await delay(120);
    const id = String(params["0"] ?? "") as "tutor-rag-f3" | "tutor-direct-f3";
    const session = state.sessions[id];
    if (!session) return error("NOT_FOUND", "Tutor 会话不存在。", 404);
    const body = z.object({ input_mode: z.literal("text").optional(), message: z.string().min(1) }).strict().parse(await request.json());
    if (session.turns.at(-1)?.status === "running") return error("TUTOR_TURN_IN_PROGRESS", "上一轮还在处理中。", 409);
    const userMessage = body.message;
    const turn: Turn = {
      id: nextId("turn"), ordinal: session.turns.length + 1, status: "running", input_mode: body.input_mode ?? "text",
      user_message: userMessage, retrieval_run_id: session.mode === "tutor_rag" ? nextId("retrieval") : null,
      next_state: null, strategy: "single_question_scaffold", message: null, source_ref_ids: [], warnings: [], error_code: null, error_message: null,
      created_at: fixedNow, completed_at: null,
    };
    session.turns.push(turn);
    session.getCount = 0;
    return HttpResponse.json({ turn, task_id: nextId("task-turn") }, { status: 202 });
  }),
  http.get(/\/api\/v1\/retrieval-runs\/retrieval-f3-\d+$/, async ({ params }) => {
    await delay(70);
    return HttpResponse.json({
      id: String(params["0"] ?? "retrieval-f3"), course_id: COURSE_ID, context_snapshot_id: "snapshot-tutor-rag-f3", tutor_turn_id: "turn-f3",
      status: "ready", raw_query: "链式法则", rewritten_queries: ["复合函数 内层导数"], retrieval_config_version: "hybrid-v1", degraded_reasons: [], evidence_count: 1,
      evidence: [{ source_ref_id: "source-f3-example", material_id: "material-f3-notes", material_version_id: "material-version-f3-v1", rank: 1, text: "外层求导后乘以内层导数。", locator: { paragraph_no: 3 }, keyword_score: 0.82, vector_score: 0.78, rerank_score: 0.91 }],
      created_at: fixedNow, completed_at: fixedNow,
    });
  }),

  http.get(/\/api\/v1\/source-refs\/source-f3-[^/]+$/, async ({ params }) => {
    await delay(60);
    const sourceId = String(params["0"] ?? "source-f3-chain");
    const text: Record<string, string> = {
      "source-f3-chain": "复合函数求导时，先识别外层函数与内层函数，再用外层导数乘以内层导数。",
      "source-f3-example": "例：y=(3x+1)²，导数是 2(3x+1)×3，最后的 3 来自内层函数。",
      "source-f3-limit": "导数由差商的极限定义；课堂第三段录音还需回听核对。",
    };
    return HttpResponse.json({
      id: sourceId, material_id: "material-f3-notes", material_version_id: "material-version-f3-v1", display_name: "微积分课堂整理.txt",
      material_type: "text", text: text[sourceId] ?? text["source-f3-chain"], locator_type: "paragraph", start_ms: null, end_ms: null,
      page_no: null, bbox: null, paragraph_no: sourceId === "source-f3-example" ? 3 : 1, confidence: 0.96,
      preview_path: "/api/v1/materials/material-f3-notes/original",
    });
  }),
  http.get("/api/v1/materials/material-f3-notes/original", () => new HttpResponse("微积分课堂原始文本（F3 合同 Mock）", { headers: { "Content-Type": "text/plain; charset=utf-8" } })),
];
