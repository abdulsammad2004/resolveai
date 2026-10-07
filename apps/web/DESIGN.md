# ResolveAI web design system: "frosted glass over deep water"

Every page reuses these tokens. They live as CSS variables and Tailwind theme values in
`src/app/globals.css`, so components use classes (`bg-seafoam`, `text-mist-dim`,
`rounded-panel`, `glass`), never raw hex values. Dark theme is the only theme for now.

## Palette

| Token | Value | Tailwind | Use |
| --- | --- | --- | --- |
| `--deep` | `#0E1B2C` | `bg-deep` | Page base, text on seafoam buttons |
| `--tide` | `#1F4E5F` | `bg-tide` | Background glows |
| `--mist` | `#E8F1F5` | `text-mist` | Primary text |
| `--mist-dim` | `#9FB4C2` | `text-mist-dim` | Secondary text |
| `--seafoam` | `#7FE0C8` | `bg-seafoam` / `text-seafoam` | Primary action, success, approved, focus ring |
| `--amber` | `#F5B85A` | `text-amber` | Awaiting review, warnings |
| `--coral` | `#FF8A7A` | `text-coral` | Urgent, errors, destructive |

shadcn's semantic variables (`--primary`, `--muted-foreground`, `--destructive`, ...) are
aliased onto this palette, so any shadcn component added later starts on-brand.

## Glass

| Utility | Recipe | Use |
| --- | --- | --- |
| `glass` | white fill 0.07 over a deep tint `rgb(14 27 44 / 0.55)`; 1px border `rgb(255 255 255 / 0.14)`; 1px inner top highlight `rgb(255 255 255 / 0.18)`; `backdrop-filter: blur(20px) saturate(140%)` | Panels, cards, secondary buttons |
| `glass-elevated` | white fill 0.11 over deep tint 0.6; same border and highlight; blur 28px | Menus, dialogs, toasts, the AI draft in the preview |
| `glass-input` | white fill 0.05 over deep tint 0.35; same border | Inputs and textareas |
| `glass-interactive` | hover raises the fill to 0.10 (animated through the registered `--glass-fill` property) | Anything glass that is clickable |

- No grey drop shadows on cards. Depth comes from the blur, the border and the inner highlight.
- **Fallback.** When `backdrop-filter` is unsupported, or the user sets
  `prefers-reduced-transparency: reduce`, the glass variables switch to solid `#16263A`
  panels (`#1A2C42` elevated) with no blur. Nothing else needs to change.

### Contrast

A 7% white fill alone fails WCAG AA: `--mist-dim` reaches only 3.4:1 over the brightest
glow. To fix it, the panel fill was increased with a translucent deep tint under the white
layer. Worst-case values below are measured over the brightest glow (tide at 0.7 with the
seafoam tint stacked on it) and over plain `--deep`:

| Text on surface | Brightest glow | Plain deep |
| --- | --- | --- |
| `--mist-dim` on `glass` | 5.0:1 | 6.7:1 |
| `--mist-dim` on `glass` (hover) | 4.6:1 | 6.1:1 |
| `--mist-dim` on `glass-input` | 5.3:1 | |
| `--mist` on `glass` | 9.1:1 | |
| `--deep` on `--seafoam` (primary button) | 11.1:1 | |
| `--mist-dim` on solid fallback | 7.1:1 | |

Status chips get the same treatment: the accent tint (16%) sits on a deep base at 60%.
Without the base, coral text on its own tint was 3.7:1. With it, all three chips are at
least 4.9:1. If you change the glow strength or a fill, recheck these numbers.

## Background

`.page-backdrop` is a fixed layer behind everything, rendered once in the root layout:

- base `--deep`
- a `--tide` radial glow at the top-left (peak 0.7) and another at the bottom-right (peak 0.6)
- a faint seafoam tint near the bottom-right (peak 0.10)
- a fractal-noise SVG at 3% opacity so the blur doesn't band

It is static. It never animates.

## Typography

Fonts load through `next/font/google`.

- **Headings:** Bricolage Grotesque, 500–700 (`font-heading`). Letter-spacing −0.015em, line-height 1.15.
- **Everything else:** Instrument Sans, 400/500/600 (`font-sans`). Line-height 1.5.

The Tailwind text scale is mapped onto the six sizes:

| Class | Size | Use |
| --- | --- | --- |
| `text-sm` | 13px | Captions, chips, helper text |
| `text-base` | 15px | Body (default) |
| `text-lg` | 18px | Lead text, card titles |
| `text-xl` | 24px | Section headings |
| `text-2xl` | 32px | Page titles on mobile |
| `text-3xl` | 44px | Page titles, stat values |

Use sentence case everywhere. No all-caps labels, and no eyebrow labels above headings.

## Shape and spacing

- Radius follows hierarchy: `rounded-panel` (24px) for page-level panels (sidebar, top bar,
  main panels), `rounded-card` (14px) for cards, inputs, buttons and menus inside panels,
  and `rounded-full` for chips, badges and avatars.
- Spacing follows an 8px grid. Glass panels get 24px padding on mobile and 32px from `sm` up
  (`GlassPanel` does this).
- The sidebar floats 12px in from the screen edges (`top-3 left-3 bottom-3`).

## Components

- **Buttons** (`components/ui/button.tsx`):
  - `primary` is solid seafoam with deep text.
  - `secondary` is glass with mist text.
  - `destructive` is coral text on glass.
  - `ghost` is for icon buttons.
  - Labels say exactly what happens ("Create workspace", "Log in"). No arrows appended.
- **Inputs:** glass-input fill, 14px radius, label above, message below, `aria-invalid`
  wired by `Form`.
- **Status chips** (`components/status-chip.tsx`): a pill with the accent as text color.
  `seafoam` "Resolved", `amber` "Awaiting review", `coral` "Urgent"; `neutral` for roles
  and sources.
- **Focus:** a 2px seafoam outline with a 2px offset on every `:focus-visible` element
  (set globally). Menu items show a seafoam inset ring instead.
- **Empty states:** a glass panel with a seafoam icon tile, a heading, and one sentence on what
  the page will do and when. Never "Coming soon".

## Motion

- **One orchestrated moment.** On first load of the app shell, the sidebar, top bar and main
  panel fade in with an 8px rise, staggered 60ms (`rise-in` with `--i`). Navigating between
  pages does not replay it, because the shell layout persists. Nothing else animates on load.
- **Interactive feedback only:**
  - hover lightens the glass fill to 0.10
  - press scales to 0.98 (`pressable`)
  - menus and toasts fade
  - the mobile nav slides in when opened
  - the session-restore screen shows an indeterminate progress bar
- **`prefers-reduced-motion: reduce`:** entrances become plain fades with no movement, press
  scaling is off, and the progress bar is static.

## Accessibility checklist

- Body text meets AA on every glass surface (see Contrast).
- Every input has a visible label. Errors are linked with `aria-describedby`, and form-level
  errors use `role="alert"`.
- There is a skip link to the main content. The mobile nav is a modal dialog that closes on
  Escape and returns focus to its button.
- Layouts work at 375px. On the auth screens the product preview is hidden below `lg`.
