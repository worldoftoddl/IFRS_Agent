import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "K-IFRS 회계 자문 AI",
  description:
    "한국채택국제회계기준(K-IFRS) 전문 AI 챗봇 — 기준서 검색 및 회계 자문",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <head>
        <link
          rel="preconnect"
          href="https://fonts.googleapis.com"
        />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
