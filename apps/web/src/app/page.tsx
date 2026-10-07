"use client";

import { LandingNav } from "@/components/landing/landing-nav";
import { HeroSection } from "@/components/landing/hero-section";
import { Marquee } from "@/components/landing/marquee";
import { ScrollDemo } from "@/components/landing/scroll-demo";
import { HowItWorks } from "@/components/landing/how-it-works";
import { ClosingCta } from "@/components/landing/closing-cta";
import { SmoothScroll } from "@/components/landing/smooth-scroll";
import { CustomCursor } from "@/components/landing/custom-cursor";
import Link from "next/link";

export default function HomePage() {
  return (
    <SmoothScroll>
      <CustomCursor />
      <div className="min-h-screen bg-ink text-bone selection:bg-ion selection:text-bone">
        <LandingNav />
        <main>
          <HeroSection />
          <Marquee />
          <ScrollDemo />
          <HowItWorks />
          <ClosingCta />
        </main>
        <footer className="border-t border-line bg-ink py-10 text-center text-sm text-ash">
          <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 sm:flex-row sm:px-6 lg:px-8">
            <p className="font-mono text-xs uppercase tracking-widest text-ash">
              ResolveAI &copy; 2026 &mdash; Grounded Autonomous Support
            </p>
            <div className="flex gap-6 text-xs">
              <Link href="/login" className="hover:text-bone transition-colors">
                Sign In
              </Link>
              <Link href="/signup" className="hover:text-bone transition-colors">
                Get Started
              </Link>
            </div>
          </div>
        </footer>
      </div>
    </SmoothScroll>
  );
}
