import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/components/providers/AppProviders";

import "./globals.css";

export const metadata: Metadata = {
  title: "笨人学习｜课后复习工作台",
  description: "把课堂材料变成可追溯、可执行的学习路径",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <a className="skip-link" href="#page-content">跳到主要内容</a>
        <div id="page-content" tabIndex={-1}>
          <AppProviders>{children}</AppProviders>
        </div>
      </body>
    </html>
  );
}
