---
version: alpha
name: Hollawall Finance
description: A calm, trustworthy financial operating workspace grounded in Hollawall orange, cyan, and navy.
colors:
  primary: "#B85C00"
  primaryHover: "#974B00"
  secondary: "#087F8A"
  brandOrange: "#FB9202"
  brandCyan: "#18B8C6"
  brandNavy: "#163746"
  canvas: "#F4F7F7"
  surface: "#FFFFFF"
  surfaceMuted: "#EEF4F5"
  text: "#173443"
  textSecondary: "#526B76"
  border: "#C9DADE"
  positive: "#14735D"
  negative: "#A83E3A"
  warning: "#8A5500"
typography:
  display:
    fontFamily: Montserrat
    fontSize: 2.4375rem
    fontWeight: 800
    lineHeight: 1.06
    letterSpacing: "-0.035em"
  heading:
    fontFamily: Montserrat
    fontSize: 1.5rem
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: Montserrat
    fontSize: 0.9375rem
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: Montserrat
    fontSize: 0.75rem
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: "0.06em"
rounded:
  sm: 8px
  md: 12px
  lg: 16px
  pill: 999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  section: 40px
components:
  application:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
  brand-mark:
    backgroundColor: "{colors.brandOrange}"
    textColor: "{colors.brandNavy}"
    rounded: "{rounded.sm}"
    size: 40px
  focus-indicator:
    backgroundColor: "{colors.brandCyan}"
    textColor: "{colors.brandNavy}"
    rounded: "{rounded.sm}"
    size: 3px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#FFFFFF"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 42px
  button-primary-hover:
    backgroundColor: "{colors.primaryHover}"
    textColor: "#FFFFFF"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 42px
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 42px
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: 16px
  card-muted:
    backgroundColor: "{colors.surfaceMuted}"
    textColor: "{colors.textSecondary}"
    rounded: "{rounded.md}"
    padding: 16px
  divider:
    backgroundColor: "{colors.border}"
    textColor: "{colors.text}"
    height: 1px
  status-positive:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.positive}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: 8px
  status-negative:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.negative}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: 8px
  status-warning:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.warning}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: 8px
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 42px
---

## Overview

Hollawall Finance is an operating workspace, not a promotional page. It should feel calm, legible, precise, and dependable. Visual hierarchy comes from spacing, typography, and restrained surfaces. Orange identifies the brand and primary action. Cyan supports navigation, focus, and analytical data. Navy anchors text and high-contrast financial context.

## Colors

- **Action orange (`#B85C00`)** is the accessible interactive version of Hollawall orange. Use it for the single primary action and active emphasis.
- **Brand orange (`#FB9202`)** is decorative. Do not place white body text on it.
- **Action cyan (`#087F8A`)** supports focus, selected analytical controls, and chart series.
- **Navy (`#163746`)** is the identity anchor for text and high-emphasis finance panels.
- Green, red, and amber are semantic only: positive, negative/destructive, and warning.
- Do not use color alone. Pair every status color with text, iconography, shape, or sign.

## Typography

Montserrat is the sole interface family. Financial values use tabular numerals. Default body text should remain at least 13px, with 15px preferred for reading copy. Text below 11px is prohibited. All-caps labels are short, sparse, and secondary.

## Layout

Use an 8px rhythm with 4px only for compact internal relationships. Desktop content uses a fluid gutter up to 36px. Mobile controls are at least 44px high. A page should expose one title, one concise description, and one primary action before its data.

## Elevation & Depth

Borders and spacing provide most separation. Shadows remain subtle and appear only on raised interactive or summary surfaces. Avoid glass effects, stacked shadows, and decorative gradients in operational screens.

## Shapes

Controls use 8px corners. Panels use 12px. Large modal or summary surfaces may use 16px. Pills are reserved for compact status chips, never general containers.

## Components

- A page has at most one orange primary button in its main header.
- Secondary buttons use a neutral surface and visible border.
- Destructive actions remain red and require explicit labels.
- Cards need a clear information purpose; do not wrap every section in a card.
- Tables align money right, use tabular numerals, and retain labels on small screens.
- Loading, empty, warning, error, and read-only states share the same spacing and tone hierarchy.

## Do's and Don'ts

- Do create hierarchy in grayscale before adding semantic color.
- Do keep financial position and required action visible near the top.
- Do use orange and cyan intentionally, not simultaneously on every component.
- Do preserve keyboard focus and a 44px mobile target.
- Don't introduce another font family, color palette, shadow style, or breakpoint without extending this system.
- Don't use hardcoded white surfaces; use semantic surface tokens for dark-mode safety.
- Don't duplicate page headings or primary actions between the shell and workspace.

## QA Record — 11 November 2026

- Production build passed with TypeScript checking and Vite bundling.
- All 30 test files and 213 tests passed on Node 24.22.2.
- Light and dark themes were reviewed at 1440 × 1000 and 390 × 844.
- Ringkasan, Proyek, and Laporan were reviewed with a representative production-shaped snapshot.
- Mobile navigation, stacked actions, local table scrolling, long headings, and status messages were checked for viewport containment.
- Keyboard focus, skip navigation, 44px mobile targets, reduced motion, loading, error, read-only, and empty-state treatments remain covered by the canonical layer.
- React `act()` and JSDOM `scrollTo` / navigation warnings remain non-fatal test-environment limitations.