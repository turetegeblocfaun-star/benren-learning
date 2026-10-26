"use client";

import { ArrowRightLeft, CheckCircle2, Link2, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Notice } from "@/components/Feedback";
import { F5Shell, F5Status } from "@/components/controlled/F5Shell";
import { crossCourseLinkListSchema, crossCourseLinkSchema, type CrossCourseLink } from "@/features/controlled/schema";
import { learningAssetSchema } from "@/features/learning/schema";
import { courseListSchema, learningAssetListSchema } from "@/features/system/schema";
import { apiFetchContract, jsonBody, presentError } from "@/lib/api/client";

export default function CrossCoursePage() {
  const [selected, setSelected] = useState<string[]>([]); const [purpose, setPurpose] = useState("把先修概念作为本课程复习辅助");
  const [sourceCourseId, setSourceCourseId] = useState(""); const [targetCourseId, setTargetCourseId] = useState("");
  const [changedLink, setChangedLink] = useState<CrossCourseLink | null>(null); const [busy, setBusy] = useState(false); const [caught, setCaught] = useState<unknown>(null);
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetchContract(courseListSchema, "/api/v1/courses?limit=100") });
  const links = useQuery({ queryKey: ["cross-course-links"], queryFn: () => apiFetchContract(crossCourseLinkListSchema, "/api/v1/cross-course-links?limit=100") });
  useEffect(() => {
    if (!courses.data?.length || sourceCourseId) return;
    const source = courses.data.find((item) => item.title?.includes("微积分")) ?? courses.data[0];
    setSourceCourseId(source.id);
    setTargetCourseId(courses.data.find((item) => item.id !== source.id)?.id ?? "");
  }, [courses.data, sourceCourseId]);
  const assets = useQuery({ queryKey: ["learning-assets", sourceCourseId], queryFn: () => apiFetchContract(learningAssetListSchema, `/api/v1/courses/${sourceCourseId}/learning-assets?limit=100`), enabled: Boolean(sourceCourseId) });
  const noteId = assets.data?.find((item) => item.asset_type === "note" && item.status !== "failed")?.id;
  const note = useQuery({ queryKey: ["learning-asset", noteId], queryFn: () => apiFetchContract(learningAssetSchema, `/api/v1/learning-assets/${noteId}`), enabled: Boolean(noteId) });
  const sourceRefs = useMemo(() => note.data?.current_version?.source_ref_ids ?? [], [note.data?.current_version?.source_ref_ids]);
  useEffect(() => { if (!selected.length && sourceRefs[0]) setSelected([sourceRefs[0]]); }, [selected.length, sourceRefs]);
  const link = changedLink ?? links.data?.[0] ?? null;
  async function create() { setBusy(true); setCaught(null); try { setChangedLink(await apiFetchContract(crossCourseLinkSchema, "/api/v1/cross-course-links", { method: "POST", body: jsonBody({ source_course_id: sourceCourseId, target_course_id: targetCourseId, selected_source_ref_ids: selected, purpose }) })); } catch (error) { setCaught(error); } finally { setBusy(false); } }
  async function revoke() { if (!link) return; setBusy(true); setCaught(null); try { setChangedLink(await apiFetchContract(crossCourseLinkSchema, `/api/v1/cross-course-links/${link.id}`, { method: "DELETE", headers: { "If-Match": String(link.version) } })); } catch (error) { setCaught(error); } finally { setBusy(false); } }
  return <F5Shell eyebrow="F5 · P2 跨课关联" title="只复用你明确选中的来源" description="跨课程关系不会自动推断或静默建立。你必须选择来源片段、目标课程和用途；创建后可版本化撤销。" gate="cross_course" backHref="/controlled">
    <section className="f5-cross-flow"><article><span>来源课程</span><select className="input" value={sourceCourseId} onChange={(event) => { setSourceCourseId(event.target.value); setSelected([]); }}>{courses.data?.map((course) => <option value={course.id} key={course.id}>{course.title ?? "未命名课程"}</option>)}</select>{sourceRefs.map((sourceRefId) => <label key={sourceRefId}><input type="checkbox" checked={selected.includes(sourceRefId)} onChange={(event) => setSelected((current) => event.target.checked ? [...new Set([...current, sourceRefId])] : current.filter((item) => item !== sourceRefId))} />来源片段 {sourceRefId}</label>)}</article><ArrowRightLeft size={27} /><article><span>目标课程</span><select className="input" value={targetCourseId} onChange={(event) => setTargetCourseId(event.target.value)}>{courses.data?.filter((course) => course.id !== sourceCourseId).map((course) => <option value={course.id} key={course.id}>{course.title ?? "未命名课程"}</option>)}</select><label className="field"><span>本次复用用途</span><textarea className="input" value={purpose} onChange={(e) => setPurpose(e.target.value)} /></label></article></section>
    <section className="f5-boundary"><ShieldCheck size={19} /><div><strong>课程、来源和已有关系均可从后端恢复</strong><p>这里只提交你勾选的 SourceRef；刷新后通过关系列表恢复，不做静默跨课推断。</p></div></section>
    {caught ? <Notice tone="error" {...presentError(caught)} /> : null}
    {!link ? <button className="button button-primary" onClick={create} disabled={busy || selected.length === 0 || !targetCourseId || purpose.trim().length < 2}><Link2 size={16} />创建显式关联</button> : <section className="f5-link-record"><CheckCircle2 size={21} /><div><div className="cluster"><strong>跨课关系已记录</strong><F5Status value={link.status} /><small>v{link.version}</small></div><p>{link.purpose}</p><span>只包含：{link.selected_source_ref_ids.join("、")}</span></div>{link.status === "active" ? <button className="button button-secondary" onClick={revoke} disabled={busy}><RotateCcw size={15} />撤销关系</button> : null}</section>}
  </F5Shell>;
}
