import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradingClaw",
  description: "Fast bet tracking dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
