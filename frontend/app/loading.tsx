export default function GlobalLoading() {
  return (
    <main className="provider-boot" aria-busy="true" aria-live="polite">
      <span className="provider-boot-mark" aria-hidden="true">笨</span>
      <p>正在打开学习工作台…</p>
    </main>
  );
}
