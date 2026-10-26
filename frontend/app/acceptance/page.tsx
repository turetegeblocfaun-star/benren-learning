"use client";

import { Check, CheckCircle2, ExternalLink, RotateCcw, ShieldCheck, Smartphone, TestTube2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { acceptanceChecks, qualityGates } from "@/features/acceptance/checks";

const STORAGE_KEY = "bl_f6_acceptance_v1";

export default function AcceptancePage() {
  const [completed, setCompleted] = useState<string[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
      if (Array.isArray(saved)) setCompleted(saved.filter((id): id is string => typeof id === "string"));
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
    setReady(true);
  }, []);

  const completedSet = useMemo(() => new Set(completed), [completed]);
  const progress = Math.round((completedSet.size / acceptanceChecks.length) * 100);

  function toggle(id: string) {
    const next = completedSet.has(id) ? completed.filter((item) => item !== id) : [...completed, id];
    setCompleted(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  function reset() {
    setCompleted([]);
    localStorage.removeItem(STORAGE_KEY);
  }

  return (
    <AppShell>
      <main className="page-wrap acceptance-page">
        <section className="acceptance-hero" aria-labelledby="acceptance-title">
          <div>
            <p className="eyebrow">F6 · 最终前端验收</p>
            <h1 id="acceptance-title">照着 12 步，检查完整学习闭环</h1>
            <p className="lede">这里是可操作的合同 Mock 验收环境，不是真实生产数据。你的勾选仅保存在当前浏览器。</p>
          </div>
          <div className="acceptance-progress" aria-live="polite" aria-atomic="true">
            <strong>{ready ? `${completedSet.size} / ${acceptanceChecks.length}` : "正在读取…"}</strong>
            <span>已验证 · {ready ? progress : 0}%</span>
          </div>
        </section>

        <section className="acceptance-boundary" aria-label="当前环境边界">
          <span><TestTube2 aria-hidden="true" />合同 Mock</span>
          <span><ShieldCheck aria-hidden="true" />无真实 API Key 进入浏览器</span>
          <span><Smartphone aria-hidden="true" />390 / 768 / 1280 / 1440px</span>
          <strong>尚未真实联调 · 尚未部署</strong>
        </section>

        <div className="acceptance-layout">
          <section className="card acceptance-checklist" aria-labelledby="manual-checks-title">
            <div className="card-head">
              <div><p className="eyebrow">手动验收</p><h2 id="manual-checks-title">产品经理可照着点</h2></div>
              <button className="button button-secondary" type="button" onClick={reset} disabled={!completed.length}><RotateCcw size={16} aria-hidden="true" />清空勾选</button>
            </div>
            <ol className="acceptance-list">
              {acceptanceChecks.map((item, index) => {
                const checked = completedSet.has(item.id);
                return (
                  <li className={checked ? "acceptance-item is-complete" : "acceptance-item"} key={item.id}>
                    <label className="acceptance-check-control">
                      <input type="checkbox" checked={checked} onChange={() => toggle(item.id)} />
                      <span className="acceptance-check-box" aria-hidden="true">{checked ? <Check size={16} /> : index + 1}</span>
                      <span><strong>{item.title}</strong><span>{item.instruction}</span></span>
                    </label>
                    {item.href ? <Link className="acceptance-deep-link" href={item.href}>{item.linkLabel}<ExternalLink size={15} aria-hidden="true" /></Link> : null}
                  </li>
                );
              })}
            </ol>
          </section>

          <aside className="acceptance-aside" aria-label="自动检查与联调边界">
            <section className="card">
              <p className="eyebrow">提交前自动门</p>
              <h2>本分支质量记录</h2>
              <p className="small muted">这是本次 F6 提交的固定检查记录，不是线上实时监控。</p>
              <ul className="quality-gates">
                {qualityGates.map((gate) => <li key={gate}><CheckCircle2 size={17} aria-hidden="true" /><span>{gate}</span></li>)}
              </ul>
            </section>
            <section className="card">
              <p className="eyebrow">联调前硬门</p>
              <h2>代码已关闭，等待真实联调验证</h2>
              <ul className="boundary-list">
                <li>课程、资产、Tutor、计划、运行记录和 P2 对象已有列表恢复合同。</li>
                <li>格式与大小读取公开能力；WebM/Opus 会在服务端校验并转为 OGG/Opus。</li>
                <li>后台任务支持查询和执行前取消；运行中会明确拒绝伪取消。</li>
                <li>Cookie 写请求校验 Origin；角色与能力由后端会话返回并再次强制。</li>
              </ul>
              <Link className="button button-secondary acceptance-wide-button" href="/controlled">查看 F5 受控能力</Link>
            </section>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}
