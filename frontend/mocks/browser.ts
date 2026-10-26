import { setupWorker } from "msw/browser";

import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);

let startPromise: ReturnType<typeof worker.start> | undefined;

export function startMockWorker() {
  startPromise ??= worker.start({
    onUnhandledRequest(request, print) {
      const pathname = new URL(request.url).pathname;
      if (pathname.startsWith("/api/v1")) print.error();
    },
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
  return startPromise;
}
