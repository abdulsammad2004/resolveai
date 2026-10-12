import type { Metadata, Viewport } from "next";
import { Big_Shoulders, Geist } from "next/font/google";

import { Providers } from "./providers";
import "./globals.css";

const displayFont = Big_Shoulders({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["700", "800", "900"],
  display: "swap",
});

const geistFont = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "ResolveAI", template: "%s · ResolveAI" },
  description: "Support that resolves itself. High-energy AI customer support automation.",
};

export const viewport: Viewport = {
  themeColor: "#0E0F12",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${displayFont.variable} ${geistFont.variable} dark`}>
      <body className="min-h-dvh bg-ink text-bone font-sans antialiased selection:bg-ion/30 selection:text-white">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
