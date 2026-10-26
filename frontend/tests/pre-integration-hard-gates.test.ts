import { describe, expect, it } from "vitest";

import { controlledGateContract } from "@/features/controlled/gates";
import { taskStatusSchema, userSchema } from "@/features/materials/schema";
import { capabilitiesSchema, courseListSchema, workflowRunListSchema } from "@/features/system/schema";

describe("pre-integration hard gate contracts", () => {
  it("requires public material upload limits without a Tutor voice contract", () => {
    const parsed = capabilitiesSchema.parse({
      api_contract_version: "v1",
      upload: {
        audio: { extensions: [".webm"], mime_types: ["audio/webm"], max_bytes: 10, max_duration_seconds: 10 },
        text: { extensions: [".txt"], mime_types: ["text/plain"], max_bytes: 10, max_duration_seconds: null },
        image: { extensions: [".png"], mime_types: ["image/png"], max_bytes: 10, max_duration_seconds: null },
        max_image_count_per_batch: 1, max_batch_items: 1, max_batch_bytes: 10, max_pdf_pages: 1,
        direct_upload_enabled: true, direct_upload_threshold_bytes: 8, direct_upload_expires_seconds: 900,
      },
      providers: { asr: { provider: "volcengine", configured: true } },
      features: { task_cancellation: true },
      security: { cookie_http_only: true, cookie_secure_in_production: true, same_site: "lax", csrf_origin_protection: true },
    });
    expect(parsed.upload.audio.extensions).toContain(".webm");
    expect("tutor_voice" in parsed.upload).toBe(false);
    expect(parsed.security.csrf_origin_protection).toBe(true);
  });

  it("requires roles, capabilities and honest cancellability", () => {
    const user = userSchema.parse({ id: "user", status: "active", roles: ["learner"], capabilities: ["learning:p0"] });
    const task = taskStatusSchema.parse({ task_id: "job", run_id: "run", job_type: "tutor_turn", target_id: "turn", status: "running", cancellable: false, error_code: null, created_at: "2026-09-01T00:00:00Z", started_at: "2026-09-01T00:00:01Z", finished_at: null });
    expect(user.capabilities).toContain("learning:p0");
    expect(task.cancellable).toBe(false);
    expect(controlledGateContract.governance.capability).toBe("governance:read");
  });

  it("accepts resource discovery lists without known frontend IDs", () => {
    expect(courseListSchema.parse([{ id: "server-course", title_status: "unnamed", title: null, version: 1, material_counts: {}, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" }])[0].id).toBe("server-course");
    expect(workflowRunListSchema.parse([{ id: "server-run", course_id: "server-course", task_type: "generate_note", status: "queued", started_at: "2026-09-01T00:00:00Z", finished_at: null }])[0].id).toBe("server-run");
  });
});
