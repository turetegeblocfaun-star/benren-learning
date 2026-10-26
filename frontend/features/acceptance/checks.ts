export type AcceptanceCheck = {
  id: string;
  title: string;
  instruction: string;
  href?: string;
  linkLabel?: string;
};

export const acceptanceChecks: AcceptanceCheck[] = [
  {
    id: "preview-marker",
    title: "确认预览身份",
    instruction: "确认页头明确写有“前端独立预览”，本页同时注明合同 Mock、尚未真实联调、尚未部署。",
    href: "/courses/new",
    linkLabel: "打开上传入口",
  },
  {
    id: "invite-direct-upload",
    title: "邀请码直达上传",
    instruction: "从登录页输入 F6 演示邀请码，确认直接进入上传页面，中间没有学科选择。",
    href: "/login?next=/courses/new",
    linkLabel: "重新验证登录",
  },
  {
    id: "mixed-materials",
    title: "上传已有材料",
    instruction: "上传音频、图片、Word（DOCX）、PDF 和 Markdown（MD），确认每一项都有明确状态和删除选项；页面不要求麦克风权限。",
    href: "/courses/demo-course-f2/materials",
    linkLabel: "进入材料页",
  },
  {
    id: "material-correction",
    title: "校正识别文字",
    instruction: "从材料列表打开一项待校正材料，修改文字并保存；返回后确认状态已经变化。",
    href: "/courses/demo-course-f2/materials",
    linkLabel: "继续材料闭环",
  },
  {
    id: "material-delete",
    title: "二次确认删除",
    instruction: "删除一项材料，确认先看到影响范围，再执行二次确认；取消时不得删除。",
    href: "/courses/demo-course-f2/materials",
    linkLabel: "继续材料闭环",
  },
  {
    id: "note-source",
    title: "笔记与来源",
    instruction: "选择材料生成结构化笔记；点击任一来源，确认能看到原文和页码、段落或时间位置。",
    href: "/courses/demo-course-f3/notes/note-f3",
    linkLabel: "打开结构化笔记",
  },
  {
    id: "graph-list",
    title: "图谱等价列表",
    instruction: "打开知识图谱并切换概念列表，确认来源、关系和掌握状态不用依赖颜色也能读懂。",
    href: "/courses/demo-course-f3/graph/graph-f3",
    linkLabel: "打开知识图谱",
  },
  {
    id: "quiz-disclosure",
    title: "测验延迟揭示答案",
    instruction: "做一道测验：提交前看不到答案，提交后能看到判分、具体解析和课堂来源。",
    href: "/courses/demo-course-f3/quizzes/quiz-f3",
    linkLabel: "打开测验",
  },
  {
    id: "tutor-text",
    title: "文字 Tutor",
    instruction: "完成文字提问，并验证 RAG 无命中时能换成材料内问题安全恢复；页面不提供录音入口。",
    href: "/courses/demo-course-f3/tutor/tutor-rag-f3",
    linkLabel: "打开 Tutor",
  },
  {
    id: "single-next-action",
    title: "唯一下一步",
    instruction: "回到课程工作台，确认页面只突出一个下一步，不同时竞争多个主操作。",
    href: "/courses/demo-course-f4/workspace",
    linkLabel: "打开复习工作台",
  },
  {
    id: "plan-confirm-undo",
    title: "计划确认与撤销",
    instruction: "生成计划、修改候选时间，先查看影响再确认写入内部日历，最后撤销并确认历史仍可追溯。",
    href: "/courses/demo-course-f4/workspace",
    linkLabel: "验证计划闭环",
  },
  {
    id: "responsive-keyboard",
    title: "电脑、手机与键盘",
    instruction: "分别用电脑和手机宽度操作；确认按钮、弹窗、导航和输入框不被遮挡，并可用 Tab、Shift+Tab、Enter、Escape 完成操作。",
  },
];

export const qualityGates = [
  "ESLint：通过",
  "TypeScript 严格检查：通过",
  "Vitest：20 项通过",
  "Playwright：40 项通过、2 项真实后端检查按阶段跳过",
  "Next.js 生产构建：通过",
] as const;
