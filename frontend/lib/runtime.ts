export const isContractMock = process.env.NEXT_PUBLIC_API_MODE === "mock";

export const runtimeStatus = isContractMock
  ? {
      badge: "前端独立预览",
      stage: "F6 · 前端验收",
      learning: "资源发现合同已接入 · 尚未真实联调",
      planning: "F4 资源发现合同已接入 · 尚未真实联调",
      controlled: "F5 受控能力 · 合同 Mock · 已知资源 ID",
    }
  : {
      badge: "真实前后端联调",
      stage: "联调验收",
      learning: "真实 API · 资源与异步状态可恢复",
      planning: "真实 API · 计划与确认状态可恢复",
      controlled: "真实 API · 后端角色与能力门禁",
    };
