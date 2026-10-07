export function CoreFallback() {
  return (
    <div className="relative flex size-full items-center justify-center" role="img" aria-label="ResolveAI Core Icon">
      <svg
        viewBox="0 0 400 400"
        className="size-[280px] sm:size-[360px] lg:size-[420px] transition-transform duration-700 ease-out hover:scale-105"
        fill="none"
      >
        <defs>
          <radialGradient id="coreGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#7B6CFF" stopOpacity="0.4" />
            <stop offset="60%" stopColor="#7B6CFF" stopOpacity="0.1" />
            <stop offset="100%" stopColor="#7B6CFF" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="facetGrad1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#8F82FF" />
            <stop offset="100%" stopColor="#5544DF" />
          </linearGradient>
          <linearGradient id="facetGrad2" x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#6C5CE7" />
            <stop offset="100%" stopColor="#3B2DB8" />
          </linearGradient>
        </defs>

        {/* Ambient Glow */}
        <circle cx="200" cy="200" r="160" fill="url(#coreGlow)" />

        {/* Faceted Core Polyhedron Geometry */}
        <g stroke="#7B6CFF" strokeWidth="1.5" strokeLinejoin="round" strokeOpacity="0.6">
          <polygon points="200,60 320,130 200,200" fill="url(#facetGrad1)" fillOpacity="0.85" />
          <polygon points="200,60 80,130 200,200" fill="url(#facetGrad2)" fillOpacity="0.9" />
          <polygon points="320,130 320,270 200,200" fill="url(#facetGrad2)" fillOpacity="0.75" />
          <polygon points="80,130 80,270 200,200" fill="url(#facetGrad1)" fillOpacity="0.7" />
          <polygon points="320,270 200,340 200,200" fill="url(#facetGrad1)" fillOpacity="0.8" />
          <polygon points="80,270 200,340 200,200" fill="url(#facetGrad2)" fillOpacity="0.95" />
        </g>

        {/* Inner Highlight Wireframe Lines */}
        <line x1="200" y1="60" x2="200" y2="340" stroke="#EEECE7" strokeWidth="1.2" strokeOpacity="0.4" />
        <line x1="80" y1="130" x2="320" y2="270" stroke="#EEECE7" strokeWidth="1" strokeOpacity="0.3" />
        <line x1="80" y1="270" x2="320" y2="130" stroke="#EEECE7" strokeWidth="1" strokeOpacity="0.3" />
      </svg>
    </div>
  );
}

