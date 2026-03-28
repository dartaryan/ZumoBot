# Zumo — Design System v2

> Citrus on Midnight. Warm amber/orange accent on true black.
> Soft, rounded, organic. Premium juice bar meets productivity tool.

---

## 1. Color Palette

### Surfaces (white-opacity layering on true black)

| Token | Name | Value | Usage |
|-------|------|-------|-------|
| `--bg-base` | Black | `#09090B` | Page background |
| `--bg-surface` | Surface | `rgba(255,255,255, 0.03)` | Cards, panels |
| `--bg-elevated` | Elevated | `rgba(255,255,255, 0.06)` | Hover, expanded panels, active tabs |
| `--bg-hover` | Hover | `rgba(255,255,255, 0.08)` | Hover states |
| `--border` | Border | `rgba(255,255,255, 0.08)` | Dividers, card borders |
| `--border-strong` | Border Strong | `rgba(255,255,255, 0.14)` | Active borders, focus |

### Accent — Citrus (gradient)

| Token | Name | Value | Usage |
|-------|------|-------|-------|
| `--accent-from` | Amber | `#F59E0B` | Gradient start, primary brand |
| `--accent-to` | Orange | `#F97316` | Gradient end |
| `--accent-text` | Gold | `#FBBF24` | Text in accent color, links |
| `--accent-muted` | Glow | `rgba(251,191,36, 0.12)` | Subtle tint fills, tag backgrounds |
| `--accent-gradient` | Citrus | `linear-gradient(135deg, #F59E0B, #F97316)` | Buttons, brand mark, accent bar |

### Text

| Token | Name | Value | Usage |
|-------|------|-------|-------|
| `--text-primary` | White | `#FAFAFA` | Headings, primary content |
| `--text-secondary` | Silver | `#A1A1AA` | Body text, descriptions |
| `--text-muted` | Zinc | `#52525B` | Timestamps, metadata, labels |

### Semantic

| Token | Name | Value | Usage |
|-------|------|-------|-------|
| `--success` | Green | `#34D399` | Analysis available, success |
| `--warning` | Gold | `#FBBF24` | Processing, pending |
| `--error` | Red | `#F87171` | Wrong password, errors |

---

## 2. Typography

**Font: Rubik** (Google Fonts) — designed for Hebrew + Latin. Rounded, friendly, excellent weight range.

```
@import url('https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700&display=swap');
```

**Display font: DM Serif Display** — serif, for the "zumo" wordmark only.

```
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&display=swap');
```

| Element | Font | Size | Weight | Color | Line Height |
|---------|------|------|--------|-------|-------------|
| Wordmark | DM Serif Display | 32px | 400 | `--accent-gradient` | 1.1 |
| Page title (H1) | Rubik | 28px | 700 | `--text-primary` | 1.2 |
| Session title (H2) | Rubik | 20px | 600 | `--text-primary` | 1.3 |
| Section header (H3) | Rubik | 16px | 600 | `--text-primary` | 1.4 |
| Body text | Rubik | 15px | 400 | `--text-secondary` | 1.7 |
| Metadata | Rubik | 13px | 500 | `--text-muted` | 1.5 |
| Button text | Rubik | 14px | 600 | Black (#000) on gradient | 1 |

---

## 3. Shape Language

**Everything is round and soft. No sharp edges.**

| Element | Border Radius |
|---------|--------------|
| Page-level cards (password gate) | `24px` (rounded-3xl) |
| Session cards | `20px` (rounded-2xl) |
| Inner content panels | `16px` (rounded-xl) |
| Buttons | `14px` (rounded-xl) |
| Input fields | `14px` (rounded-xl) |
| Icon containers | `12px` (rounded-xl) |
| Pills / badges | `100px` (fully round) |
| Tab bar | `0` (flat inside card) |

**Stroke weight:** All icons use 2.5px stroke (thicker than standard 2px). Rounded line caps and joins.

---

## 4. Layout

- **Direction:** `dir="rtl"` — Hebrew RTL
- **Max width:** `max-w-3xl` (768px) — tight reading column
- **Background:** Full-page `--bg-base` with ambient gradient orbs (barely visible)
- **Content padding:** `px-5 md:px-8`
- **Ambient mesh:** Two large blurred orbs (amber + purple, `opacity: 0.07`, `filter: blur(120px)`) fixed in background

### Page Structure

```
[Full-screen Password Gate]
        |
        v
[Sticky Header — glass blur]
    Zumo logo icon + wordmark         Session count pill

[Session List]
    [Session Card] — collapsed (rounded-2xl, accent gradient bar on right)
    [Session Card] — expanded (tabs + content panel)
    ...

[Footer — minimal]
```

---

## 5. Components

### Password Gate

- Full viewport, centered
- Card: `bg-surface`, `rounded-3xl` (24px), `border`, `max-w-sm`, `backdrop-blur`
- Zumo logo icon + wordmark at top (DM Serif, citrus gradient)
- Lock icon (Lucide `Lock`, 40px, `--text-muted`, `opacity: 0.5`)
- Input: `bg-elevated`, `rounded-xl` (14px), `text-center`, thick border on focus
- Button: citrus gradient background, black text, `rounded-xl`, full width
- Error: red border + shake animation + error text

### Sticky Header

- `bg-base` at 70% opacity + `backdrop-blur(20px)`
- `border-b border`
- `rounded-2xl` with margin from edges (floating style)
- Zumo icon + "zumo" wordmark (DM Serif, citrus gradient)
- Session count: pill badge `bg-accent-muted`, `text-accent-text`, fully rounded

### Session Cards

- `bg-surface`, `border`, `rounded-2xl` (20px)
- Right-edge accent bar: 3px wide, citrus gradient, `rounded`
- Icon container: 38px, `rounded-xl`, `bg-accent-muted`, icon in `--accent-text`
- Hover: `bg-elevated`, `border-strong`
- Expanded: tabs + content panel inside

### Tab Bar

- Inside expanded card, below card header
- Active tab: `--accent-text` color, bottom border `--accent-from`
- Inactive tab: `--text-muted`

### Type Icons (Lucide, 18px, stroke-width 2.5)

| Type | Icon |
|------|------|
| Team Meeting | `Users` |
| Training | `GraduationCap` |
| Client Call | `Handshake` |
| Phone Call | `Phone` |
| Coaching | `Lightbulb` |
| Other | `FileText` |

All icons rendered in `--accent-text` (#FBBF24).

---

## 6. Effects & Interactions

| Element | Effect | Duration |
|---------|--------|----------|
| Card hover | bg + border shift | 200ms ease |
| Card expand/collapse | Height + fade | 200ms ease-out |
| Tab switch | Color crossfade | 150ms |
| Link hover | `--accent-text` -> lighter | 150ms |
| Button hover | Slight opacity (0.9) + translateY(-1px) | 200ms |
| Password error | Shake keyframe (6px, 3 cycles) | 300ms |
| Focus ring | `box-shadow: 0 0 0 2px base, 0 0 0 4px accent/40%` | instant |

**Gradient usage:** Only on accent bar, buttons, and the wordmark. Everything else is flat.

---

## 7. Spacing Scale

4px base: `4, 8, 12, 16, 24, 32, 48, 64`

- Between session cards: `8px`
- Card internal padding: `16px 20px`
- Content panel padding: `24px`
- Section spacing in markdown: `24px`
- Page top padding (below header): `24px`

---

## 8. Responsive Breakpoints

| Screen | Width | Adjustments |
|--------|-------|-------------|
| Mobile | < 640px | `px-4`, H1 24px, H2 18px, full-width cards |
| Tablet | 640-1024px | `px-6`, standard sizes |
| Desktop | > 1024px | `px-8`, `max-w-3xl` centered |

---

## 9. Accessibility

- All text exceeds WCAG AA 4.5:1 contrast on `--bg-base`
- `--text-primary` (#FAFAFA) on #09090B = 19.4:1
- `--text-secondary` (#A1A1AA) on #09090B = 7.2:1
- `--text-muted` (#52525B) on #09090B = 4.6:1
- Focus: visible ring on all interactive elements
- Reduced motion: `@media (prefers-reduced-motion: reduce)` disables all transitions
- Keyboard: full tab navigation, Enter to expand, Escape to close

---

## 10. Brand Mark

**Logo icon:** Phone handset + orange slice mashup. The curved phone receiver shape filled with citrus segment lines. Single icon, works at all sizes.

**Wordmark:** "zumo" in DM Serif Display, citrus gradient (`#F59E0B -> #F97316`).

**Lockup:** Icon + wordmark side by side. Icon on the right (RTL).

---

## 11. Anti-patterns

- No emojis anywhere in the UI
- No sharp corners (minimum 12px radius)
- No thin 1px strokes on icons (use 2.5px)
- No pure white backgrounds
- No blue accent (we use citrus amber/orange)
- No box-shadows (depth comes from layered opacity surfaces)
- No JavaScript frameworks (vanilla JS only)
