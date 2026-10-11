import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Butler — 企业知识助手",
  description: "跨平台查资料，按权限给答案。体验 Butler 的结论级防护。",
  icons: { icon: "/butler-avatar.png", apple: "/butler-avatar.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-scroll-behavior="smooth">
      <body>
        {children}
      </body>
    </html>
  );
}
