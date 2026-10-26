import { apiFetch } from "@/lib/api/client";

import {
  courseDetailSchema,
  materialListSchema,
  workspaceResponseSchema,
  type WorkspaceView,
} from "./schema";

export async function getWorkspaceView(courseId: string): Promise<WorkspaceView> {
  const [courseValue, workspaceValue, materialsValue] = await Promise.all([
    apiFetch<unknown>(`/api/v1/courses/${courseId}`),
    apiFetch<unknown>(`/api/v1/courses/${courseId}/workspace`),
    apiFetch<unknown>(`/api/v1/courses/${courseId}/materials`),
  ]);

  const course = courseDetailSchema.parse(courseValue);
  const workspace = workspaceResponseSchema.parse(workspaceValue);
  const materials = materialListSchema.parse(materialsValue);

  return { course, workspace, materials: materials.items };
}
