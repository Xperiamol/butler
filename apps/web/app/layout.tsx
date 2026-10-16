import type { Metadata } from "next";
import "./globals.css";
import "./motion.css";
import MotionEffects from "@/components/MotionEffects";

export const metadata: Metadata = {
  title: "Butler — 企业知识助手",
  description: "跨平台查资料，按权限给答案。体验 Butler 的结论级防护。",
  icons: { icon: "/butler-avatar.png", apple: "/butler-avatar.png" },
};

// Runs before first paint: enables the reveal animations and skips the intro for return visits.
const EARLY = "try{var d=document.documentElement;d.classList.add('js');if(sessionStorage.getItem('butler-intro')==='1')d.dataset.seen='1'}catch(e){document.documentElement.classList.add('js')}";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: EARLY }} /></head>
      <body>
        <MotionEffects />
        {children}
      </body>
    </html>
  );
}
