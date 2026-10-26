"use client";

import {
  ArrowRight,
  CheckCircle2,
  FileAudio,
  FileText,
  Image as ImageIcon,
  PenLine,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { AppShell, StepStrip } from "@/components/AppShell";
import { DeleteDialog } from "@/components/DeleteDialog";
import { EmptyState, LoadingCard, Notice } from "@/components/Feedback";
import { StatusChip } from "@/components/StatusChip";
import {
  batchSchema,
  courseSchema,
  deletePreviewSchema,
  deleteResponseSchema,
  directUploadPrepareSchema,
  materialListSchema,
  taskRefSchema,
  titleCandidateSchema,
} from "@/features/materials/schema";
import { capabilitiesSchema, type SystemCapabilities } from "@/features/system/schema";
import {
  AppError,
  apiFetchContract,
  idempotencyKey,
  jsonBody,
  presentError,
} from "@/lib/api/client";
import type {
  Batch,
  Course,
  Material,
  TitleCandidateResponse,
} from "@/lib/api/types";
import { formatBytes, materialStatus, materialTypeLabel } from "@/lib/status";

type MaterialType = Material["declared_type"];
type SelectedFile = { file: File; type: MaterialType };
type DeleteState = {
  material: Material;
  confirmationId: string;
  impact: Record<string, unknown>;
};
type UploadManifestItem = {
  client_item_id: string;
  declared_type: MaterialType;
  upload_index?: number;
  text?: string;
  display_name: string;
};

const TERMINAL_MATERIALS = new Set([
  "usable",
  "needs_review",
  "partial",
  "failed",
]);

const uploadKindDefinitions: {
  type: MaterialType;
  label: string;
  multiple: boolean;
  Icon: typeof FileAudio;
}[] = [
  {
    type: "audio",
    label: "音频文件",
    multiple: true,
    Icon: FileAudio,
  },
  {
    type: "text",
    label: "Word / PDF / Markdown",
    multiple: true,
    Icon: FileText,
  },
  {
    type: "board_image",
    label: "图片（板书）",
    multiple: true,
    Icon: ImageIcon,
  },
  {
    type: "handwriting_image",
    label: "图片（手写笔记）",
    multiple: true,
    Icon: PenLine,
  },
];

function MaterialIcon({ type }: { type: string }) {
  const Icon =
    type === "audio"
      ? FileAudio
      : type === "text"
        ? FileText
        : type === "board_image"
          ? ImageIcon
          : PenLine;
  return <Icon size={20} aria-hidden="true" />;
}

export default function MaterialsPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<Course | null>(null);
  const [capabilities, setCapabilities] = useState<SystemCapabilities | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [titleCandidate, setTitleCandidate] =
    useState<TitleCandidateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<{
    message: string;
    detail?: string;
  } | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([]);
  const [pastedText, setPastedText] = useState("");
  const [uploadKey, setUploadKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [lastBatch, setLastBatch] = useState<Batch | null>(null);
  const [busyMaterialId, setBusyMaterialId] = useState<string | null>(null);
  const [deleteState, setDeleteState] = useState<DeleteState | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [titleChoice, setTitleChoice] = useState("");
  const [manualTitle, setManualTitle] = useState("");
  const [titleBusy, setTitleBusy] = useState(false);

  const handleAuthError = useCallback(
    (caught: unknown) => {
      if (caught instanceof AppError && caught.status === 401) {
        router.replace(
          `/login?next=${encodeURIComponent(`/courses/${courseId}/materials`)}`,
        );
        return true;
      }
      return false;
    },
    [courseId, router],
  );

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setRefreshing(true);
      try {
        const [nextCourse, materialResponse, systemCapabilities] = await Promise.all([
          apiFetchContract(courseSchema, `/api/v1/courses/${courseId}`),
          apiFetchContract(materialListSchema,
            `/api/v1/courses/${courseId}/materials`,
          ),
          apiFetchContract(capabilitiesSchema, "/api/v1/capabilities"),
        ]);
        let nextCandidate: TitleCandidateResponse | null = null;
        if (nextCourse.title_status !== "confirmed") {
          try {
            nextCandidate = await apiFetchContract(titleCandidateSchema,
              `/api/v1/courses/${courseId}/title-candidate`,
            );
          } catch (caught) {
            if (
              !(
                caught instanceof AppError &&
                caught.code === "TITLE_SCOPE_EMPTY"
              )
            )
              throw caught;
          }
        }
        setCourse(nextCourse);
        setCapabilities(systemCapabilities);
        setMaterials(materialResponse.items);
        setTitleCandidate(nextCandidate);
        const recent = {
          id: nextCourse.id,
          title: nextCourse.title ?? "未命名课程",
          savedAt: new Date().toISOString(),
        };
        localStorage.setItem("bl_recent_course", JSON.stringify(recent));
        setError(null);
      } catch (caught) {
        if (!handleAuthError(caught)) setError(presentError(caught));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [courseId, handleAuthError],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  const shouldPoll = useMemo(() => {
    const materialRunning = materials.some(
      (material) => !TERMINAL_MATERIALS.has(material.status),
    );
    const titleRunning =
      course?.title_status !== "confirmed" &&
      materials.some((material) => material.status === "usable") &&
      !titleCandidate;
    return (
      materialRunning ||
      titleRunning ||
      lastBatch?.status === "processing" ||
      lastBatch?.status === "pending"
    );
  }, [course?.title_status, lastBatch?.status, materials, titleCandidate]);

  const uploadKinds = useMemo(() => uploadKindDefinitions.map((item) => {
    const capability = item.type === "audio"
      ? capabilities?.upload.audio
      : item.type === "text"
        ? capabilities?.upload.text
        : capabilities?.upload.image;
    return {
      ...item,
      help: capability
        ? `${capability.extensions.map((value) => value.slice(1).toUpperCase()).join("、")} · 单份不超过 ${formatBytes(capability.max_bytes)}`
        : "正在读取后端支持格式…",
      accept: capability ? [...capability.extensions, ...capability.mime_types].join(",") : "",
    };
  }), [capabilities]);

  useEffect(() => {
    if (!shouldPoll) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void load(true);
    }, 2200);
    return () => window.clearInterval(timer);
  }, [load, shouldPoll]);

  function chooseFiles(type: MaterialType, files: FileList | null) {
    if (!files) return;
    setSelectedFiles((current) => [
      ...current.filter((item) => item.type !== type),
      ...Array.from(files).map((file) => ({ file, type })),
    ]);
  }

  function removeSelectedFile(targetIndex: number) {
    setSelectedFiles((current) => current.filter((_, index) => index !== targetIndex));
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!selectedFiles.length && !pastedText.trim()) return;
    setUploading(true);
    setError(null);
    const items: UploadManifestItem[] = selectedFiles.map((item, index) => {
      return {
        client_item_id: `file-${index}-${Date.now()}`,
        declared_type: item.type,
        upload_index: index,
        display_name: item.file.name,
      };
    });
    if (pastedText.trim())
      items.push({
        client_item_id: `paste-${Date.now()}`,
        declared_type: "text",
        text: pastedText.trim(),
        display_name: "粘贴的课堂文字.txt",
      });
    try {
      const selectedBytes = selectedFiles.reduce(
        (total, item) => total + item.file.size,
        0,
      );
      const useDirectUpload = Boolean(
        selectedFiles.length &&
        capabilities?.upload.direct_upload_enabled &&
        selectedBytes >= capabilities.upload.direct_upload_threshold_bytes,
      );
      let batch: Batch;
      if (useDirectUpload) {
        const prepared = await apiFetchContract(
          directUploadPrepareSchema,
          `/api/v1/courses/${courseId}/direct-upload-urls`,
          {
            method: "POST",
            body: jsonBody({
              items: selectedFiles.map((item, index) => ({
                client_item_id: items[index].client_item_id,
                declared_type: item.type,
                display_name: item.file.name,
                byte_size: item.file.size,
              })),
            }),
          },
        );
        const filesByClientId = new Map(
          selectedFiles.map((item, index) => [items[index].client_item_id, item.file]),
        );
        for (const ticket of prepared.items) {
          const file = filesByClientId.get(ticket.client_item_id);
          if (!file)
            throw new AppError(
              "DIRECT_UPLOAD_CONTRACT_MISMATCH",
              "大文件上传清单发生变化，请重新选择文件。",
            );
          let response: Response;
          try {
            response = await fetch(ticket.upload_url, { method: "PUT", body: file });
          } catch {
            throw new AppError(
              "DIRECT_UPLOAD_NETWORK_ERROR",
              "大文件上传到私有存储失败，请检查网络后重试。",
            );
          }
          if (!response.ok)
            throw new AppError(
              "DIRECT_UPLOAD_FAILED",
              "大文件上传没有成功，请重新选择文件后再试。",
              undefined,
              response.status,
            );
        }
        batch = await apiFetchContract(
          batchSchema,
          `/api/v1/courses/${courseId}/direct-material-batches`,
          {
            method: "POST",
            headers: { "Idempotency-Key": idempotencyKey("direct-upload") },
            body: jsonBody({
              upload_tokens: prepared.items.map((item) => item.upload_token),
              text_items: pastedText.trim()
                ? [{
                    client_item_id: `paste-${Date.now()}`,
                    display_name: "粘贴的课堂文字.txt",
                    text: pastedText.trim(),
                  }]
                : [],
            }),
          },
        );
      } else {
        const form = new FormData();
        selectedFiles.forEach((item) => form.append("files", item.file));
        form.append("manifest", JSON.stringify({ items }));
        batch = await apiFetchContract(
          batchSchema,
          `/api/v1/courses/${courseId}/material-batches`,
          {
            method: "POST",
            headers: { "Idempotency-Key": idempotencyKey("upload") },
            body: form,
          },
        );
      }
      setLastBatch(batch);
      setSelectedFiles([]);
      setPastedText("");
      setUploadKey((value) => value + 1);
      await load(true);
    } catch (caught) {
      if (!handleAuthError(caught)) setError(presentError(caught));
    } finally {
      setUploading(false);
    }
  }

  async function retryMaterial(material: Material) {
    setBusyMaterialId(material.id);
    setError(null);
    try {
      await apiFetchContract(taskRefSchema, `/api/v1/materials/${material.id}/retry`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("retry") },
        body: jsonBody({ expected_version: material.version }),
      });
      await load(true);
    } catch (caught) {
      setError(presentError(caught));
    } finally {
      setBusyMaterialId(null);
    }
  }

  async function previewDelete(material: Material) {
    setBusyMaterialId(material.id);
    setError(null);
    try {
      const preview = await apiFetchContract(deletePreviewSchema, `/api/v1/materials/${material.id}/deletion-preview`, {
        method: "POST",
        body: jsonBody({ expected_version: material.version }),
      });
      setDeleteState({
        material,
        confirmationId: preview.confirmation_id,
        impact: preview.impact,
      });
    } catch (caught) {
      setError(presentError(caught));
    } finally {
      setBusyMaterialId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteState) return;
    setDeleting(true);
    setError(null);
    try {
      await apiFetchContract(deleteResponseSchema, `/api/v1/materials/${deleteState.material.id}`, {
        method: "DELETE",
        body: jsonBody({
          confirmation_id: deleteState.confirmationId,
          expected_version: deleteState.material.version,
        }),
      });
      setDeleteState(null);
      await load(true);
    } catch (caught) {
      setError(presentError(caught));
    } finally {
      setDeleting(false);
    }
  }

  async function confirmTitle(event: FormEvent) {
    event.preventDefault();
    if (!course) return;
    const edited = manualTitle.trim();
    if (!titleChoice && !edited) return;
    setTitleBusy(true);
    setError(null);
    try {
      const confirmed = await apiFetchContract(courseSchema,
        `/api/v1/courses/${courseId}/title-confirmations`,
        {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey("title") },
          body: jsonBody({
            candidate_id: edited ? null : titleChoice,
            edited_title: edited || null,
            expected_course_version: course.version,
          }),
        },
      );
      setCourse(confirmed);
      setTitleCandidate(null);
      setTitleChoice("");
      setManualTitle("");
      localStorage.setItem(
        "bl_recent_course",
        JSON.stringify({
          id: confirmed.id,
          title: confirmed.title ?? "未命名课程",
          savedAt: new Date().toISOString(),
        }),
      );
    } catch (caught) {
      setError(presentError(caught));
    } finally {
      setTitleBusy(false);
    }
  }

  async function regenerateTitle() {
    if (!course) return;
    setTitleBusy(true);
    setTitleCandidate(null);
    setError(null);
    try {
      await apiFetchContract(taskRefSchema, `/api/v1/courses/${courseId}/title-candidate:regenerate`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("retitle") },
        body: jsonBody({ expected_course_version: course.version }),
      });
      window.setTimeout(() => void load(true), 900);
    } catch (caught) {
      setError(presentError(caught));
    } finally {
      setTitleBusy(false);
    }
  }

  if (loading)
    return (
      <AppShell>
        <main className="page-wrap">
          <LoadingCard label="正在恢复课程与材料状态…" />
        </main>
      </AppShell>
    );
  const usableCount = materials.filter(
    (material) => material.status === "usable",
  ).length;

  return (
    <AppShell>
      <main className="page-wrap">
        <StepStrip active={1} />
        <div className="page-head">
          <div className="page-head-copy">
            <p className="eyebrow">课程材料</p>
            <h1>{course?.title ?? "让材料替这门课命名"}</h1>
            <p className="lede">
              一次可以混合上传四类材料。后台会独立处理每一份，某一份失败不会拖住整批。
            </p>
          </div>
          <button
            className="button button-secondary"
            onClick={() => void load()}
            disabled={refreshing}
          >
            <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            {refreshing ? "刷新中" : "刷新状态"}
          </button>
        </div>
        {error ? (
          <div style={{ marginBottom: 18 }}>
            <Notice tone="error" {...error} />
          </div>
        ) : null}
        {lastBatch ? (
          <div style={{ marginBottom: 18 }}>
            <Notice
              tone={lastBatch.failed_count ? "info" : "success"}
              message={`最近批次：${lastBatch.status === "completed" ? "处理完成" : lastBatch.status === "failed" ? "处理失败" : "后台处理中"}（${lastBatch.success_count}/${lastBatch.item_count} 可用）`}
              detail={
                shouldPoll
                  ? "你可以停留或离开页面，任务会在后台继续。"
                  : undefined
              }
            />
          </div>
        ) : null}

        <form className="card" onSubmit={upload}>
          <div className="card-head">
            <div>
              <p className="eyebrow">01 · 收集</p>
              <h2>添加这一课的原始材料</h2>
              <p className="muted">
                系统会检查真实文件类型；只改文件后缀不会绕过校验。
              </p>
              <p className="muted">
                支持上传已有音频、JPG/PNG/WEBP 图片、Word（DOCX）、PDF 和 Markdown（MD）；本页面不调用麦克风录音。
              </p>
            </div>
            <Upload size={22} />
          </div>
          <div className="upload-grid" key={uploadKey}>
            {uploadKinds.map(
              ({ type, label, help, accept, multiple, Icon }) => {
                const count = selectedFiles.filter(
                  (item) => item.type === type,
                ).length;
                return (
                  <div className="upload-zone" key={type}>
                    <div className="upload-zone-head">
                      <span className="material-icon">
                        <Icon size={19} />
                      </span>
                      <div>
                        <h3>{label}</h3>
                        <span className="small muted">{help}</span>
                      </div>
                    </div>
                    <input
                      className="file-input"
                      type="file"
                      accept={accept}
                      multiple={multiple}
                      onChange={(event) =>
                        chooseFiles(type, event.target.files)
                      }
                      aria-label={`选择${label}`}
                    />
                    {count ? (
                      <p
                        className="small"
                        style={{ marginTop: 9, marginBottom: 0 }}
                      >
                        已选择 {count} 份
                      </p>
                    ) : null}
                  </div>
                );
              },
            )}
          </div>
          <div className="divider" />
          {capabilities ? <p className="field-help">本次以后端公开能力为准：最多 {capabilities.upload.max_batch_items} 份、总计不超过 {formatBytes(capabilities.upload.max_batch_bytes)}；图片每批最多 {capabilities.upload.max_image_count_per_batch} 张，PDF 最多 {capabilities.upload.max_pdf_pages} 页。</p> : null}
          <div className="field">
            <label htmlFor="pasted-text">或者直接粘贴课堂文字</label>
            <textarea
              id="pasted-text"
              className="textarea"
              value={pastedText}
              onChange={(event) => setPastedText(event.target.value)}
              placeholder="粘贴老师发的提纲、课堂总结或你已经整理好的文字…"
            />
            <span className="field-help">
              粘贴内容会作为一份独立文本材料保存并参与课程命名。
            </span>
          </div>
          {selectedFiles.length ? (
            <ul className="selected-files selected-file-list" aria-label="待上传文件">
              {selectedFiles.map((item, index) => (
                <li key={`${item.file.name}-${index}`}>
                  <span>{materialTypeLabel(item.type)} · {item.file.name} · {formatBytes(item.file.size)}</span>
                  <button
                    className="button button-ghost button-small"
                    type="button"
                    aria-label={`移除待上传文件 ${item.file.name}`}
                    onClick={() => removeSelectedFile(index)}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="cluster" style={{ marginTop: 20 }}>
            <button
              className="button button-primary"
              type="submit"
              disabled={
                uploading || (!selectedFiles.length && !pastedText.trim())
              }
            >
              {uploading ? (
                "正在安全上传…"
              ) : (
                <>
                  <Upload size={17} />
                  上传并开始识别
                </>
              )}
            </button>
            <span className="small muted">
              上传后可以关闭页面，刷新会恢复真实状态。
            </span>
          </div>
        </form>

        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">02 · 核对</p>
              <h2>材料处理状态</h2>
              <p className="muted">
                低置信内容不会直接混进上下文；先点“查看与校正”。
              </p>
            </div>
            <span className="stage-pill">{materials.length} 份材料</span>
          </div>
          {!materials.length ? (
            <EmptyState
              title="还没有材料"
              text="从上面的四类入口选择文件，或直接粘贴一段文字。"
            />
          ) : (
            <div className="material-list">
              {materials.map((material) => {
                const status = materialStatus(material.status);
                return (
                  <article className="material-row" key={material.id}>
                    <div className="material-main">
                      <span className="material-icon">
                        <MaterialIcon type={material.declared_type} />
                      </span>
                      <div>
                        <div className="cluster">
                          <span className="material-name">
                            {material.display_name}
                          </span>
                          <StatusChip {...status} />
                        </div>
                        <div className="material-meta">
                          <span>
                            {materialTypeLabel(material.declared_type)}
                          </span>
                          <span>{formatBytes(material.byte_size)}</span>
                          <span>版本 {material.version}</span>
                        </div>
                        {material.error_message ? (
                          <p
                            className="small"
                            style={{
                              color: "var(--danger)",
                              margin: "7px 0 0",
                            }}
                          >
                            {material.error_message}
                          </p>
                        ) : null}
                      </div>
                    </div>
                    <div className="material-actions">
                      {material.active_parse_version_id ? (
                        <Link
                          className="button button-secondary button-small"
                          href={`/materials/${material.id}/review`}
                        >
                          {material.status === "needs_review"
                            ? "查看与校正"
                            : "查看结果"}
                        </Link>
                      ) : null}
                      {material.retryable ? (
                        <button
                          className="button button-secondary button-small"
                          onClick={() => void retryMaterial(material)}
                          disabled={busyMaterialId === material.id}
                        >
                          <RotateCcw size={14} />
                          重试
                        </button>
                      ) : null}
                      <button
                        className="button button-delete button-small"
                        aria-label={`删除资料 ${material.display_name}`}
                        onClick={() => void previewDelete(material)}
                        disabled={
                          busyMaterialId === material.id ||
                          material.status === "deleting"
                        }
                      >
                        <Trash2 size={15} />
                        删除资料
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">03 · 命名</p>
              <h2>
                {course?.title_status === "confirmed"
                  ? "课程名称已确认"
                  : "确认课程名称"}
              </h2>
              <p className="muted">
                候选只引用本课已经可用的材料，你也可以自己改。
              </p>
            </div>
            <Sparkles size={22} />
          </div>
          {course?.title_status === "confirmed" ? (
            <div className="notice notice-success">
              <CheckCircle2 size={18} />
              <p>
                <strong>{course.title}</strong> 已成为这门课程的正式名称。
              </p>
            </div>
          ) : titleCandidate?.candidates.length ? (
            <form className="stack" onSubmit={confirmTitle}>
              {titleCandidate.candidates.map((candidate) => (
                <label className="candidate" key={candidate.id}>
                  <input
                    type="radio"
                    name="title"
                    value={candidate.id}
                    checked={titleChoice === candidate.id && !manualTitle}
                    onChange={() => {
                      setTitleChoice(candidate.id);
                      setManualTitle("");
                    }}
                  />
                  <span>
                    <span className="candidate-title">{candidate.title}</span>
                    <br />
                    <span className="small muted">
                      依据 {candidate.source_ref_ids.length} 个来源 · 置信度{" "}
                      {Math.round(candidate.confidence * 100)}%
                    </span>
                  </span>
                  <span className="cluster">
                    {candidate.source_ref_ids.slice(0, 2).map((id) => (
                      <Link
                        className="button button-ghost button-small"
                        href={`/sources/${id}`}
                        key={id}
                        onClick={(event) => event.stopPropagation()}
                      >
                        看来源
                      </Link>
                    ))}
                  </span>
                </label>
              ))}
              <div className="field">
                <label htmlFor="manual-title">或者自己填写</label>
                <input
                  id="manual-title"
                  className="input"
                  value={manualTitle}
                  maxLength={30}
                  onChange={(event) => {
                    setManualTitle(event.target.value);
                    if (event.target.value) setTitleChoice("");
                  }}
                  placeholder="最多 30 个字"
                />
              </div>
              <div className="cluster">
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={titleBusy || (!titleChoice && !manualTitle.trim())}
                >
                  {titleBusy ? "正在确认…" : "确认课程名称"}
                </button>
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => void regenerateTitle()}
                  disabled={titleBusy}
                >
                  <RefreshCw size={15} />
                  重新生成
                </button>
              </div>
            </form>
          ) : (
            <div className="notice notice-info">
              <Sparkles size={18} />
              <p>
                {usableCount
                  ? "正在根据可用材料生成候选名称…"
                  : "至少有一份材料处理为“可以使用”后，才会生成名称候选。"}
              </p>
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">下一步</p>
              <h2>把可用材料编排成完整上下文</h2>
              <p className="muted">
                当前有 {usableCount} 份材料可以进入快照。待校正材料需要先处理。
              </p>
            </div>
          </div>
          <Link
            className="button button-primary"
            aria-disabled={!usableCount}
            tabIndex={usableCount ? 0 : -1}
            style={
              !usableCount
                ? { pointerEvents: "none", opacity: 0.48 }
                : undefined
            }
            href={`/courses/${courseId}/context`}
          >
            选择材料并验证上下文 <ArrowRight size={17} />
          </Link>
        </section>
        {deleteState ? (
          <DeleteDialog
            name={deleteState.material.display_name}
            impact={deleteState.impact}
            busy={deleting}
            onCancel={() => setDeleteState(null)}
            onConfirm={() => void confirmDelete()}
          />
        ) : null}
      </main>
    </AppShell>
  );
}
