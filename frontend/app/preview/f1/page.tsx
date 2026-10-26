import type { Metadata } from "next";

import { WorkspaceShell } from "@/components/layout/WorkspaceShell";
import { WorkspacePreview } from "@/features/workspace/WorkspacePreview";

export const metadata: Metadata = {
  title: "F1 今日工作台｜笨人学习",
  description: "笨人学习正式前端 F1 代表工作台独立预览",
};

export default function FrontendStageOnePreviewPage() {
  return (
    <WorkspaceShell>
      <WorkspacePreview />
    </WorkspaceShell>
  );
}
