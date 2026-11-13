import type { Metadata, Viewport } from "next";
import { Nunito } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const nunito = Nunito({ subsets: ["latin"], variable: "--font-nunito", display: "swap" });

export const metadata: Metadata = {
  title: "NL Housing",
  description: "Rotterdam rentals, read and explained in English.",
};

// Lets the bottom bar sit above the iPhone home indicator (env(safe-area-inset-bottom)).
export const viewport: Viewport = { viewportFit: "cover", themeColor: "#f6efe8" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={nunito.variable}>
      <body>{children}</body>
    </html>
  );
}
