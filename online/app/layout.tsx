import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "行意 · 二手车咨询 Agent",
  description: "DeepSeek 工具调用、买卖匹配与批量咨询分流。独立个人作品，合成数据。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
