# Strategy2560 Design System Master

> **Generated:** 2026-05-13
> **Category:** Financial Analytics Dashboard
> **Theme:** Dark Mode (OLED)

## Hierarchical Retrieval

1. When building a specific page, first check `design-system/pages/[page-name].md`
2. If the page file exists, its rules **override** this Master file
3. If not, strictly follow the rules below

---

## Color Palette

| Role | Hex | CSS Variable | Usage |
|------|-----|-------------|-------|
| Background | `#020617` | `--bg` | Page body |
| Surface | `#0F172A` | `--surface` | Sidebar, code blocks, inputs |
| Panel | `#1E293B` | `--panel` | Cards, panels, tables |
| Primary | `#3B82F6` | `--blue` | Links, data viz, focus rings |
| Primary Hover | `#2563EB` | `--blue2` | Button hover states |
| CTA / Positive | `#22C55E` | `--green` | Success indicators, positive badges |
| Text Primary | `#F8FAFC` | `--text` | Body text |
| Text Muted | `#94A3B8` | `--muted` | Secondary text, labels |
| Border | `#334155` | `--line` | Dividers, input borders |
| Danger | `#EF4444` | `--danger` | Errors, cancel buttons |
| Warning | `#F59E0B` | `--warning` | Cautions, stale labels |
| Info | `#38BDF8` | `--info` | Info highlights |

**Color Notes:** Dark-first dashboard. Blue for data interaction, green for positive status, amber for warnings.

## Typography

- **Headings:** Fira Code (wght@400;500;600;700)
- **Body:** Fira Sans (wght@300;400;500;600;700)
- **Mood:** dashboard, data, analytics, code, technical, precise
- **Google Fonts:** `Fira Code:wght@400;500;600;700|Fira+Sans:wght@300;400;500;600;700`

```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

## Spacing & Layout

| Token | Value | Usage |
|-------|-------|-------|
| `--radius` | `16px` | Card/panel border radius |
| `--transition` | `200ms ease-out` | Hover transitions, focus transitions |
| `--shadow` | `0 12px 30px rgba(0,0,0,.3)` | Card shadow |
| Sidebar width | `280px` | Desktop, sticky left |
| Breakpoints | `1100px`, `760px` | Grid collapse, mobile stack |

## Effects

- **Transitions:** `200ms ease-out` for hover, focus, and state changes
- **Focus-visible:** `outline: 2px solid var(--blue); outline-offset: 2px`
- **Button hover:** subtle `box-shadow` glow, no layout shift
- **Card hover:** shadow increase only, no scale transform
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` — all transitions set to `0.01ms`

## Component Patterns

### Buttons

| Class | Style | Use |
|-------|-------|-----|
| `.primary` | Blue bg, white text, blue shadow on hover | Main actions (load, run, refresh) |
| `.ghost` | Panel bg, border, hover to darker panel | Cancel, secondary actions |
| `.soft` | Semi-transparent blue, blue text | Select current, select by filter |
| `.probe-btn` | Blue bg | Market scan buttons |
| `.probe-btn.danger` | Surface bg, hover to `#334155` | Full-market destructive actions |

### Badges

| Class | Style | Use |
|-------|-------|-----|
| `.badge.ok` | Green bg tint, `#4ade80` text | 结构完整 |
| `.badge.mid` | Amber bg tint, `#fbbf24` text | 部分满足 |
| `.badge.bad` | Red bg tint, `#f87171` text | 明显缺失 |
| `.badge.gray` | Gray bg tint, `#cbd5e1` text | 数据不足/unknown |

### Progress Bars

- Track: `#334155` (dark), `8px` height, rounded
- Fill: `#3B82F6` (blue) or `#22C55E` (green for completion)
- Label: `12px`, primary color `#F8FAFC`, muted secondary `#94A3B8`

### Tables

- Header: `var(--surface)` bg, `var(--muted)` text, `700` weight
- Rows: `var(--line)` border-bottom
- Hover: `rgba(59,130,246,.05)` bg tint
- Selected: `rgba(59,130,246,.15)` bg

### Forms

- Input bg: `var(--surface)`, text: `var(--text)`
- Border: `var(--line)`
- Focus: blue border + `3px rgba(59,130,246,.15)` glow
- Placeholder: `#64748b`

## Chart Colors (8-color palette)

```
0: #3B82F6  (blue)
1: #EF4444  (red)
2: #F59E0B  (amber)
3: #22C55E  (green)
4: #8B5CF6  (purple)
5: #06B6D4  (cyan)
6: #F43F5E  (rose)
7: #64748B  (slate)
```

## Sidebar Navigation (Accordion)

- Top-level items always visible
- Groups collapsible, all collapsed by default
- Only one group open at a time (accordion behavior)
- Click collapsed group's child item → auto-expand that group
- Group title chevron: down when open, rotated 90° when closed
- Active item: blue left-border + `rgba(59,130,246,.15)` bg

## Anti-Patterns

- Light mode default
- Emojis as icons (use SVG: Heroicons/Lucide)
- Layout-shifting hover states (no scale transforms)
- Slow animations (>500ms for UI interactions)
- Invisible focus states (keyboard navigation must be visible)
- Low contrast text in light mode (4.5:1 minimum)

## Pre-Delivery Checklist

- [ ] No emojis as icons
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed elements
- [ ] No horizontal scroll on mobile
