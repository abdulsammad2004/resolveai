# ResolveAI Web Design System: Kinetic High-Energy Precision

A bold, fast, kinetic visual identity designed for modern AI customer support workflows. 
Depth comes from high-contrast dark surfaces, razor-sharp 1px borders, and purposeful motion — not glassmorphism or soft drop shadows.

## 1. Palette

| Token | Hex / Value | Tailwind / CSS | Role |
| --- | --- | --- | --- |
| `--ink` | `#0E0F12` | `bg-ink` | Base page canvas background |
| `--carbon` | `#17191E` | `bg-carbon` | Main surfaces, panels, cards, inputs |
| `--line` | `rgba(255,255,255,0.08)` | `border-line` | Structural 1px borders & dividers |
| `--bone` | `#EEECE7` | `text-bone` | Primary high-contrast text |
| `--ash` | `#8B9099` | `text-ash` | Secondary text, captions, inactive icons |
| `--ion` | `#7B6CFF` | `bg-ion` / `text-ion` / `ring-ion` | Singular brand accent: primary buttons, active bars, focus rings |
| `--resolved` | `#4FD1A5` | `text-resolved` / `bg-resolved/10` | Status only: resolved tickets, operational systems |
| `--review` | `#FFB547` | `text-review` / `bg-review/10` | Status only: drafts awaiting human review |
| `--urgent` | `#FF5C5C` | `text-urgent` / `bg-urgent/10` | Status only: errors, escalations, urgent items |

### Contrast & Legibility (WCAG AA Compliance)
- `--bone` (#EEECE7) on `--ink` (#0E0F12) has a contrast ratio of 16.2:1.
- `--bone` (#EEECE7) on `--carbon` (#17191E) has a contrast ratio of 14.1:1.
- `--ash` (#8B9099) on `--carbon` (#17191E) achieves 5.2:1 (exceeds WCAG AA 4.5:1 requirement).
- Deep text (#0E0F12) on `--ion` (#7B6CFF) has 5.6:1 contrast for high-visibility primary buttons.

## 2. Typography

Fonts load through `next/font/google`:
- **Display Typeface**: `Big Shoulders Display`, weights 700, 800, 900 (`--font-display`).
  - Tight tracking (`tracking-tight`), uppercase or sentence-case punchy sizing.
  - Used BIG: 64–160px on landing hero/closing, 40–56px in app greetings, large metrics.
- **Body & UI Typeface**: `Geist`, weights 400, 500, 600 (`--font-sans`).
  - Base body size: 15px with 1.5 line height.
  - Crisp, technical, neutral legibility.

### Rules
- Sentence case everywhere. No all-caps eyebrow labels above headings.
- Action-oriented button copy ("Create workspace", "Log in", "Start free"). No appended arrows (→).

## 3. Shape & Geometry

- **Sharp & Confident**:
  - `rounded-control` (6px): Inputs, buttons, chips, dropdown menu items, tabs.
  - `rounded-panel` (16px): Main panels, app shell sidebar/topbar, dialogs, bento cards.
- **No Glass Blur**: Replaced with solid `--carbon` surfaces with `--line` borders.
- **No Soft Grey Shadows**: Depth is created strictly via tonal contrast, subtle inner borders, and kinetic hover elevation.

## 4. Motion & Micro-Interactions

Motion is fast, physical, and purposeful:
- **Button Feedback**: `scale(0.97)` on active click/press (`pressable`).
- **Route Transitions**: Quick fade + 8px slide between routes (`≤200ms`).
- **Sidebar Rail**: Active navigation item is highlighted with an ion bar that slides smoothly between items (`layoutId` shared layout animation).
- **Status Pulse**: Live operational dots pulse with a subtle CSS keyframe ring.
- **Landing Animations**:
  - Hero staggered kinetic text reveal on load.
  - Interactive 3D faceted violet core reacting to mouse cursor (lazy-loaded R3F with static SVG fallback).
  - Pinned GSAP ScrollTrigger demo (inquiry typing → source lighting → AI drafting → approval).
  - Smooth Lenis scrolling and dynamic ion dot cursor.

### Accessibility (`prefers-reduced-motion`)
- Entrances instantly switch to static or simple zero-offset opacity fades.
- 3D core canvas renders as a lightweight static geometric SVG.
- Lenis and custom cursor are disabled.
