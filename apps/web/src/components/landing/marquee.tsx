export function Marquee() {
  const items = [
    "Answers from your docs",
    "Cites every source",
    "Drafts replies",
    "Humans approve",
    "Isolated per workspace",
  ];

  return (
    <section className="relative w-full overflow-hidden border-y border-line bg-carbon py-4 sm:py-5">
      {/* Side gradient fade masks */}
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-16 sm:w-28 bg-gradient-to-r from-carbon to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16 sm:w-28 bg-gradient-to-l from-carbon to-transparent" />

      <div className="animate-marquee flex items-center gap-8 whitespace-nowrap">
        {/* Render twice for seamless loop */}
        {[...items, ...items, ...items, ...items].map((item, index) => (
          <div key={index} className="flex items-center gap-8">
            <span className="font-display text-xl sm:text-2xl font-bold tracking-tight text-bone">
              {item}
            </span>
            <span className="size-2 rounded-full bg-ion" aria-hidden />
          </div>
        ))}
      </div>
    </section>
  );
}

