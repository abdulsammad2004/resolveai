import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Instrument_Sans } from "next/font/google";

import { Providers } from "./providers";
import "./globals.css";

const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

const instrument = Instrument_Sans({
  variable: "--font-instrument",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: { default: "ResolveAI", template: "%s · ResolveAI" },
  description: "AI drafts the reply. Your team approves it.",
};

export const viewport: Viewport = {
  themeColor: "#0E1B2C",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${bricolage.variable} ${instrument.variable}`}>
      <body className="min-h-dvh">
        <div className="page-backdrop" aria-hidden />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
