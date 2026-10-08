import type { Metadata } from "next";
import { Suspense } from "react";

import { ChatWidget } from "@/components/widget/chat-widget";

export const metadata: Metadata = { title: "Chat", robots: { index: false } };

// Rendered inside the iframe that public/widget.js injects into a customer's website.
// No app shell; the key is runtime data, so it is read inside a Suspense boundary.
export default function WidgetPage({ params }: PageProps<"/widget/[publicKey]">) {
  return (
    <Suspense fallback={<div className="h-dvh bg-ink" />}>
      {params.then(({ publicKey }) => (
        <ChatWidget publicKey={decodeURIComponent(publicKey)} />
      ))}
    </Suspense>
  );
}
