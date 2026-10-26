"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="provider-boot provider-boot-error" role="alert">
      <p className="eyebrow">页面暂时没有准备好</p>
      <h1>这一步没有打开</h1>
      <p>你不需要重新填写内容。请先重试；如果仍然失败，把当前页面截图发给开发者。</p>
      <button className="ws-button ws-button-primary" type="button" onClick={reset}>重新打开</button>
    </main>
  );
}
