import type { Metadata } from "next";

import { WidgetDemo } from "@/components/widget/widget-demo";

export const metadata: Metadata = { title: "Widget demo", robots: { index: false } };

export default function WidgetDemoPage() {
  return <WidgetDemo />;
}
