import { delay, http, HttpResponse } from "msw";

import { f2Handlers } from "./f2-handlers";
import { f3Handlers } from "./f3-handlers";
import { f4Handlers } from "./f4-handlers";
import { f5Handlers } from "./f5-handlers";
import { f6Handlers } from "./f6-handlers";

const now = "2026-08-31T13:20:00+08:00";

export const handlers = [
  http.get("/api/v1/courses/demo-course", async () => {
    await delay(180);
    return HttpResponse.json({
      id: "demo-course",
      title_status: "confirmed",
      title: "微积分 · 导数与极限",
      version: 4,
      created_at: "2026-08-27T09:00:00+08:00",
      updated_at: now,
      material_counts: {
        usable: 6,
        needs_review: 1,
        failed: 0,
      },
    });
  }),

  http.get("/api/v1/courses/demo-course/workspace", async () => {
    await delay(260);
    return HttpResponse.json({
      course_id: "demo-course",
      action: {
        type: "note_review",
        target_id: "asset-note-demo",
        reason: "昨天整理的笔记已经可以复习，先用 12 分钟回忆三个核心概念，再进入检验。",
        duration_min: 12,
        plan_id: "plan-demo",
      },
      derived_by: "workflow",
    });
  }),

  http.get("/api/v1/courses/demo-course/materials", async () => {
    await delay(220);
    return HttpResponse.json({
      items: [
        {
          id: "material-audio-demo",
          course_id: "demo-course",
          batch_id: "batch-demo",
          declared_type: "audio",
          detected_type: "audio",
          display_name: "第 3 讲课堂音频.m4a",
          detected_mime: "audio/mp4",
          byte_size: 18_420_000,
          status: "usable",
          active_parse_version_id: "parse-audio-v2",
          error_code: null,
          error_message: null,
          retryable: false,
          version: 2,
          created_at: "2026-08-30T15:20:00+08:00",
          updated_at: now,
          jobs: [],
        },
        {
          id: "material-board-demo",
          course_id: "demo-course",
          batch_id: "batch-demo",
          declared_type: "board_image",
          detected_type: "board_image",
          display_name: "板书 · 链式法则.png",
          detected_mime: "image/png",
          byte_size: 2_180_000,
          status: "usable",
          active_parse_version_id: "parse-board-v1",
          error_code: null,
          error_message: null,
          retryable: false,
          version: 1,
          created_at: "2026-08-30T15:22:00+08:00",
          updated_at: now,
          jobs: [],
        },
        {
          id: "material-note-demo",
          course_id: "demo-course",
          batch_id: "batch-demo",
          declared_type: "handwriting_image",
          detected_type: "handwriting_image",
          display_name: "手写笔记 · 极限定义.webp",
          detected_mime: "image/webp",
          byte_size: 1_640_000,
          status: "needs_review",
          active_parse_version_id: "parse-note-v1",
          error_code: null,
          error_message: null,
          retryable: false,
          version: 1,
          created_at: "2026-08-30T15:24:00+08:00",
          updated_at: now,
          jobs: [],
        },
      ],
      next_cursor: null,
    });
  }),

  ...f6Handlers,
  ...f5Handlers,
  ...f4Handlers,
  ...f3Handlers,
  ...f2Handlers,
];
