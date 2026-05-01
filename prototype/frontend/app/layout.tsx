import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Universal SQL — Prototype",
  description: "Cross-app SQL across SaaS systems",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
