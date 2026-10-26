"use client";

import { useQueries } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, FileText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { sourceRefSchema } from "@/features/materials/schema";
import { apiFetchContract } from "@/lib/api/client";
import { locatorLabel } from "@/lib/status";
import styles from "./TutorSources.module.css";

const PAGE_SIZE = 6;

export function TutorSources({ sourceIds, kind }: {
  sourceIds: string[];
  kind: "cited" | "material_scope";
}) {
  const [open, setOpen] = useState(false);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const ids = [...new Set(sourceIds)];
  const visible = ids.slice(0, limit);
  const sources = useQueries({ queries: visible.map((id) => ({
    queryKey: ["source-ref", id],
    queryFn: () => apiFetchContract(sourceRefSchema, `/api/v1/source-refs/${id}`),
    enabled: open,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })) });

  if (!ids.length) return null;

  return (
    <details className={styles.sources} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className={styles.summary}>
        <FileText size={15} aria-hidden="true" />
        <span>{kind === "cited" ? `查看本轮引用（${ids.length} 处）` : `查看材料范围（${ids.length} 段）`}</span>
        <ChevronDown className={styles.chevron} size={15} aria-hidden="true" />
      </summary>
      {open ? <div className={styles.panel}>
        {kind === "material_scope" ? <div className={styles.note}>这条历史回复未记录具体引用，以下是当时提供给 Tutor 的材料范围。</div> : null}
        <ol className={styles.list}>
          {visible.map((id, index) => {
            const query = sources[index];
            const source = query.data;
            return <li key={id}>
              <Link className={styles.link} href={`/sources/${id}`}>
                <span className={styles.title}>{source ? source.display_name : `材料片段 ${index + 1}`}</span>
                <span className={styles.location}>{source ? locatorLabel(source) : query.isError ? "查看来源详情" : "正在读取位置…"}<ExternalLink size={12} aria-hidden="true" /></span>
              </Link>
              <div className={styles.excerpt}>{source ? source.text : query.isError ? "暂时无法读取预览，可进入来源页重试。" : "正在读取原文片段…"}</div>
            </li>;
          })}
        </ol>
        {visible.length < ids.length ? <button className={styles.more} type="button" onClick={() => setLimit((value) => value + PAGE_SIZE)}>再显示 {Math.min(PAGE_SIZE, ids.length - visible.length)} 处来源</button> : null}
      </div> : null}
    </details>
  );
}
