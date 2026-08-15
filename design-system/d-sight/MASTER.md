# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** D-Sight
**Generated:** 2026-08-06 23:50:53
**Category:** Financial Dashboard
**Theme Support:** Light + Dark (Dual Theme)

---

## Global Rules

### Color Palette (Dual Theme)

#### Light Mode (`[data-theme="light"]` or default)

| Role | Hex | CSS Variable | Usage |
|------|-----|--------------|-------|
| Primary | `#1E40AF` | `--color-primary` | Headings, primary buttons |
| Secondary | `#3B82F6` | `--color-secondary` | Links, secondary accents |
| CTA/Accent | `#F59E0B` | `--color-cta` | Call-to-action buttons, highlights |
| Background | `#F8FAFC` | `--color-background` | Page background |
| Surface | `#FFFFFF` | `--color-surface` | Cards, modals, dropdowns |
| Surface Elevated | `#F1F5F9` | `--color-surface-elevated` | Elevated cards on hover |
| Border | `#E2E8F0` | `--color-border` | Dividers, input borders |
| Text Primary | `#0F172A` | `--color-text-primary` | Main body text |
| Text Secondary | `#475569` | `--color-text-secondary` | Secondary text, captions |
| Text Muted | `#94A3B8` | `--color-text-muted` | Disabled, placeholder |
| Success | `#22C55E` | `--color-success` | Positive indicators |
| Warning | `#F59E0B` | `--color-warning` | Alerts, warnings |
| Error | `#EF4444` | `--color-error` | Error states |

#### Dark Mode (`[data-theme="dark"]`)

| Role | Hex | CSS Variable | Usage |
|------|-----|--------------|-------|
| Primary | `#60A5FA` | `--color-primary` | Headings, primary buttons (brighter for dark) |
| Secondary | `#93C5FD` | `--color-secondary` | Links, secondary accents |
| CTA/Accent | `#FBBF24` | `--color-cta` | Call-to-action buttons (warmer gold) |
| Background | `#020617` | `--color-background` | Deep black background |
| Surface | `#0F172A` | `--color-surface` | Cards, modals, dropdowns |
| Surface Elevated | `#1E293B` | `--color-surface-elevated` | Elevated cards on hover |
| Border | `#334155` | `--color-border` | Dividers, input borders |
| Text Primary | `#F8FAFC` | `--color-text-primary` | Main body text (near white) |
| Text Secondary | `#CBD5E1` | `--color-text-secondary` | Secondary text |
| Text Muted | `#64748B` | `--color-text-muted` | Disabled, placeholder |
| Success | `#4ADE80` | `--color-success` | Positive indicators (brighter green) |
| Warning | `#FBBF24` | `--color-warning` | Alerts, warnings |
| Error | `#F87171` | `--color-error` | Error states (softer red) |

**Color Notes:**
- Light mode: Blue data + amber highlights
- Dark mode: Brighter blues (#60A5FA) and amber (#FBBF24) for OLED readability
- All dark text colors pass WCAG AAA on #020617 background

### CSS Variable Implementation

```css
:root {
  /* Light mode (default) */
  --color-primary: #1E40AF;
  --color-secondary: #3B82F6;
  --color-cta: #F59E0B;
  --color-background: #F8FAFC;
  --color-surface: #FFFFFF;
  --color-surface-elevated: #F1F5F9;
  --color-border: #E2E8F0;
  --color-text-primary: #0F172A;
  --color-text-secondary: #475569;
  --color-text-muted: #94A3B8;
  --color-success: #22C55E;
  --color-warning: #F59E0B;
  --color-error: #EF4444;
}

[data-theme="dark"] {
  /* Dark mode overrides */
  --color-primary: #60A5FA;
  --color-secondary: #93C5FD;
  --color-cta: #FBBF24;
  --color-background: #020617;
  --color-surface: #0F172A;
  --color-surface-elevated: #1E293B;
  --color-border: #334155;
  --color-text-primary: #F8FAFC;
  --color-text-secondary: #CBD5E1;
  --color-text-muted: #64748B;
  --color-success: #4ADE80;
  --color-warning: #FBBF24;
  --color-error: #F87171;
}
```

### Theme Toggle Implementation

```html
<!-- Theme toggle button -->
<button class="theme-toggle" aria-label="Toggle dark mode">
  <!-- Sun icon (shown in dark mode) -->
  <svg class="sun-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
    <circle cx="12" cy="12" r="5"/>
    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
  </svg>
  <!-- Moon icon (shown in light mode) -->
  <svg class="moon-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
  </svg>
</button>
```

```javascript
// Theme toggle logic
const toggleTheme = () => {
  const html = document.documentElement;
  const currentTheme = html.getAttribute('data-theme');
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
};

// Initialize theme
const initTheme = () => {
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = savedTheme || (prefersDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', theme);
};

initTheme();
```

### Typography

- **Heading Font:** Fira Code
- **Body Font:** Fira Sans
- **Mood:** dashboard, data, analytics, code, technical, precise
- **Google Fonts:** [Fira Code + Fira Sans](https://fonts.google.com/share?selection.family=Fira+Code:wght@400;500;600;700|Fira+Sans:wght@300;400;500;600;700)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

**Font Stack:**
```css
--font-heading: 'Fira Code', 'SF Mono', Monaco, monospace;
--font-body: 'Fira Sans', -apple-system, BlinkMacSystemFont, sans-serif;
```

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |

### Shadow Depths (Theme Aware)

| Level | Light Mode | Dark Mode | Usage |
|-------|------------|-----------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | `0 1px 2px rgba(0,0,0,0.3)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | `0 4px 6px rgba(0,0,0,0.4)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | `0 10px 15px rgba(0,0,0,0.5)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | `0 20px 25px rgba(0,0,0,0.5)` | Hero images, featured cards |
| `--shadow-glow` | `none` | `0 0 20px rgba(96,165,250,0.15)` | Primary glow (dark only) |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: var(--color-cta);
  color: #0F172A; /* Dark text on amber for contrast */
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
  border: none;
}

[data-theme="dark"] .btn-primary {
  color: #020617; /* Even darker for dark mode */
}

.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: var(--color-primary);
  border: 2px solid var(--color-primary);
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-secondary:hover {
  background: var(--color-primary);
  color: white;
}

[data-theme="dark"] .btn-secondary:hover {
  color: #020617;
}
```

### Cards

```css
.card {
  background: var(--color-surface);
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: pointer;
  border: 1px solid var(--color-border);
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
  background: var(--color-surface-elevated);
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
  background: var(--color-surface);
  color: var(--color-text-primary);
}

.input:focus {
  border-color: var(--color-primary);
  outline: none;
  box-shadow: 0 0 0 3px rgba(30, 64, 175, 0.2);
}

[data-theme="dark"] .input:focus {
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.2);
}

.input::placeholder {
  color: var(--color-text-muted);
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

[data-theme="dark"] .modal-overlay {
  background: rgba(0, 0, 0, 0.7);
}

.modal {
  background: var(--color-surface);
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
  border: 1px solid var(--color-border);
}
```

### Theme Toggle Button

```css
.theme-toggle {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 200ms ease;
}

.theme-toggle:hover {
  background: var(--color-surface-elevated);
  color: var(--color-text-primary);
}

/* Show/hide icons based on theme */
[data-theme="light"] .sun-icon,
[data-theme="dark"] .moon-icon {
  display: none;
}

[data-theme="dark"] .sun-icon,
[data-theme="light"] .moon-icon {
  display: block;
}
```

---

## Style Guidelines

**Style:** Professional Financial Dashboard

**Keywords:** Data-driven, clean, trustworthy, modern, accessible, dual-theme

**Best For:** Financial analytics, data visualization, professional tools, SaaS dashboards

**Key Effects:**
- Smooth theme transitions (no flash on load)
- Consistent spacing and alignment
- High contrast for data readability
- Subtle shadows for depth
- No emojis - professional icon set only

### Page Pattern

**Pattern Name:** Data Dashboard Layout

- **Structure:** Fixed sidebar + scrollable content area
- **Header:** Logo, search, notifications, theme toggle, user menu
- **Content Grid:** Responsive card-based layout
- **Charts:** Clean, minimal grid lines, clear data colors
- **Tables:** Striped rows, hover states, clear headers

---

## Anti-Patterns (Do NOT Use)

- ❌ **Flash on theme switch** — Always initialize theme before render
- ❌ **Light mode default** — Respect `prefers-color-scheme`
- ❌ **Slow rendering** — Optimize for 60fps

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y
- ❌ **Theme flash on load** — Set theme in `<head>` before body render
- ❌ **Hard-coded colors** — Always use CSS variables

---

## Theme-Specific Guidelines

### Light Mode
- Use subtle shadows for elevation (`shadow-sm`, `shadow-md`)
- White cards on light gray background (#F8FAFC)
- Dark text (#0F172A) for maximum readability
- Blue accents (#1E40AF) for primary actions

### Dark Mode
- Use elevated backgrounds for cards (#0F172A on #020617)
- Brighter accent colors (#60A5FA instead of #1E40AF)
- Slightly stronger shadows (higher opacity)
- Optional subtle glow on primary elements
- Pure black (#020617) background for OLED power saving

### Theme Transition
```css
/* Apply to all themed elements */
* {
  transition: background-color 200ms ease, color 150ms ease, border-color 200ms ease;
}

/* Respect reduced motion */
@media (prefers-reduced-motion: reduce) {
  * {
    transition: none !important;
  }
}
```

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

### Visual Quality
- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] Brand logos are correct (verified from Simple Icons)
- [ ] Hover states don't cause layout shift
- [ ] Use theme colors via CSS variables

### Both Themes
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Dark mode: text contrast 4.5:1 minimum
- [ ] Cards visible in both themes
- [ ] Borders visible in both themes
- [ ] No flash on theme switch

### Interaction
- [ ] All clickable elements have `cursor-pointer`
- [ ] Hover states provide clear visual feedback
- [ ] Transitions are smooth (150-300ms)
- [ ] Focus states visible for keyboard navigation

### Theme Toggle
- [ ] Toggle works without page reload
- [ ] Theme persists across sessions (localStorage)
- [ ] Respects system preference on first visit
- [ ] No flash on initial load

### Accessibility
- [ ] `prefers-reduced-motion` respected
- [ ] All images have alt text
- [ ] Form inputs have labels
- [ ] Color is not the only indicator

### Responsive
- [ ] Responsive at 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
