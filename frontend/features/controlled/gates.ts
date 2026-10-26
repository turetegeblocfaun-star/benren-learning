export type ControlledGate =
  | "practice"
  | "external_calendar"
  | "organization"
  | "cross_course"
  | "sft"
  | "governance";

export const controlledGateContract: Record<ControlledGate, { capability: string; label: string }> = {
  practice: { capability: "practice:subjective", label: "主观自评能力" },
  external_calendar: { capability: "calendar:external", label: "外部日历能力" },
  organization: { capability: "organization:manage", label: "组织管理员能力" },
  cross_course: { capability: "cross_course:manage", label: "跨课程管理能力" },
  sft: { capability: "sft:manage", label: "SFT 管理能力" },
  governance: { capability: "governance:read", label: "内部治理读取能力" },
};
