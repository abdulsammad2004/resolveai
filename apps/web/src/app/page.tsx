"use client";

import { LandingNav } from "@/components/landing/landing-nav";
import { HeroSection } from "@/components/landing/hero-section";
import { Marquee } from "@/components/landing/marquee";
import { TryItPlayground } from "@/components/landing/try-it-playground";
import { HowItWorks } from "@/components/landing/how-it-works";
import { RagScene } from "@/components/landing/rag-scene";
import { CapabilitiesBento } from "@/components/landing/capabilities-bento";
import { BeforeAfterSlider } from "@/components/landing/before-after-slider";
import { ScrollDemo } from "@/components/landing/scroll-demo";
import { ClosingCta } from "@/components/landing/closing-cta";
import { SiteFooter } from "@/components/landing/site-footer";
import { SmoothScroll } from "@/components/landing/smooth-scroll";
import { CustomCursor } from "@/components/landing/custom-cursor";

export default function HomePage() {
  return (
    <SmoothScroll>
      <CustomCursor />
      <div className="min-h-screen bg-ink text-bone selection:bg-ion selection:text-bone">
        <LandingNav />
        <main>
          <HeroSection />
          <Marquee />
          <TryItPlayground />
          <HowItWorks />
          <RagScene />
          <CapabilitiesBento />
          <BeforeAfterSlider />
          <ScrollDemo />
          <ClosingCta />
        </main>
        <SiteFooter />
      </div>
    </SmoothScroll>
  );
}
