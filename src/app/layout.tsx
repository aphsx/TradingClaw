import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Thunderpick",
  description: "Fast bet tracking dashboard with a thunder betting theme",
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
