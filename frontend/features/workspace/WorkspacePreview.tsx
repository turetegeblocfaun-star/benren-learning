"use client";

import {
  ArrowRight,
  AudioLines,
  Check,
  FileImage,
  FileText,
  FolderUp,
  ScanText,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { type ChangeEvent, type DragEvent, useState } from "react";

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function formatLocalFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function mergeFiles(current: File[], incoming: File[]) {
  const known = new Set(current.map(fileKey));
  return [...current, ...incoming.filter((file) => !known.has(fileKey(file)))];
}

export function WorkspacePreview() {
  const [files, setFiles] = useState<File[]>([]);
  const [pastedText, setPastedText] = useState("");
  const [dragging, setDragging] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const hasMaterial = files.length > 0 || pastedText.trim().length > 0;

  const addSelectedFiles = (event: ChangeEvent<HTMLInputElement>) => {
    setFiles((current) => mergeFiles(current, Array.from(event.target.files ?? [])));
    setSubmitted(false);
    event.target.value = "";
  };

  const acceptDroppedFiles = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    setFiles((current) => mergeFiles(current, Array.from(event.dataTransfer.files)));
    setSubmitted(false);
  };

  return (
    <div className="ws-workspace ws-intake-workspace">
      <section className="ws-intake-hero" aria-labelledby="workspace-title">
        <div>
          <p className="ws-kicker"><span>START HERE</span><span>无需先选学科或课程</span></p>
          <h1 id="workspace-title">先把材料交给我，<br />再决定它属于哪门课。</h1>
          <p>上传已有音频、图片、Word、PDF 或 Markdown 文件。系统读取内容后才会建议课程名称，由你确认后建立学习空间。</p>
        </div>
        <aside className="ws-intake-principle">
          <Sparkles size={18} aria-hidden="true" />
          <span><small>唯一开始动作</small><strong>上传一份学习材料</strong></span>
        </aside>
      </section>

      <section className="ws-upload-card" aria-labelledby="upload-title">
        <div className="ws-upload-heading">
          <span className="ws-card-step" aria-hidden="true">01</span>
          <div><p className="ws-section-no">MATERIAL INTAKE</p><h2 id="upload-title">上传学习材料</h2><p>可以一次上传多份，课程名称会根据材料内容生成。</p></div>
        </div>

        <label
          className={`ws-dropzone ${dragging ? "ws-dropzone-dragging" : ""}`}
          htmlFor="learning-materials"
          onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={acceptDroppedFiles}
        >
          <input
            id="learning-materials"
            className="sr-only"
            type="file"
            aria-label="选择学习材料文件"
            multiple
            accept="audio/*,image/*,.txt,.md,.pdf,.docx"
            onChange={addSelectedFiles}
          />
          <span className="ws-dropzone-icon" aria-hidden="true"><FolderUp size={28} strokeWidth={1.6} /></span>
          <strong>点击选择，或者把文件拖到这里</strong>
          <p>支持音频、图片、Word（DOCX）、PDF 和 Markdown（MD）文件</p>
          <span className="ws-button ws-button-primary">选择文件</span>
        </label>

        <div className="ws-format-row" aria-label="支持的材料类型">
          <span><AudioLines size={16} /><b>音频文件</b><small>MP3 · M4A · WAV</small></span>
          <span><FileText size={16} /><b>文档文件</b><small>DOCX · PDF · MD</small></span>
          <span><FileImage size={16} /><b>图片</b><small>JPG · PNG · WEBP</small></span>
        </div>

        {files.length > 0 ? (
          <div className="ws-selected-files" aria-live="polite">
            <div className="ws-selected-head"><strong>已选择 {files.length} 份材料</strong><button type="button" onClick={() => { setFiles([]); setSubmitted(false); }}>全部移除</button></div>
            {files.map((file) => (
              <div className="ws-selected-file" key={fileKey(file)}>
                <span className="ws-file-icon"><FileText size={17} /></span>
                <span><strong>{file.name}</strong><small>{formatLocalFileSize(file.size)}</small></span>
                <button type="button" aria-label={`移除文件 ${file.name}`} onClick={() => { setFiles((current) => current.filter((item) => fileKey(item) !== fileKey(file))); setSubmitted(false); }}><X size={17} /></button>
              </div>
            ))}
          </div>
        ) : null}

        <div className="ws-paste-divider"><span>或者直接粘贴课堂文字</span></div>
        <label className="ws-paste-field">
          <span>课堂文字</span>
          <textarea
            value={pastedText}
            onChange={(event) => { setPastedText(event.target.value); setSubmitted(false); }}
            placeholder="例如：老师讲到，函数在某一点的导数可以理解为曲线在该点切线的斜率……"
          />
          <small>不需要整理格式，识别完成后再由你确认。</small>
        </label>

        <div className="ws-upload-actions">
          <p><ShieldCheck size={16} />课程不会提前创建，也不会根据文件名直接猜测。</p>
          <button className="ws-button ws-button-primary ws-upload-submit" type="button" disabled={!hasMaterial} onClick={() => setSubmitted(true)}>
            上传并识别内容<ArrowRight size={17} />
          </button>
        </div>

        {submitted ? (
          <div className="ws-intake-success" role="status">
            <Check size={18} />
            <div><strong>上传入口验证通过</strong><p>下一步将识别材料内容并给出课程名称候选；在你确认以前，系统不会显示“当前课程”。</p></div>
          </div>
        ) : null}
      </section>

      <section className="ws-after-upload" aria-labelledby="after-upload-title">
        <div className="ws-panel-head">
          <div><p className="ws-section-no">WHAT HAPPENS NEXT</p><h2 id="after-upload-title">上传之后，系统才判断课程</h2></div>
        </div>
        <ol>
          <li><span>1</span><div><strong>识别材料</strong><p>读取已上传音频、图片和文档中的实际内容</p></div><ScanText size={18} /></li>
          <li><span>2</span><div><strong>建议课程名称</strong><p>根据内容生成候选，不使用预设学科</p></div><Sparkles size={18} /></li>
          <li><span>3</span><div><strong>由你确认</strong><p>确认后才创建课程并进入学习工作台</p></div><ShieldCheck size={18} /></li>
        </ol>
      </section>

      <footer className="ws-preview-foot">
        <span>F1 · FIRST ENTRY &amp; MATERIAL INTAKE SHELL</span>
        <span>数据模式：CONTRACT MOCK</span>
      </footer>
    </div>
  );
}
