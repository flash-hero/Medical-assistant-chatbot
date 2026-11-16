# Ausculta brand

Ausculta is a sourced health-information and hospital front-desk assistant in English, French and Arabic.
The brand has to read as calm, clinical-grade and trustworthy, never as a gadget, and it must work
right-to-left as well as left-to-right.

## Design read

```
Direction:           Clinical calm (quiet editorial UI, one deep spruce accent, generous white space)
Motion personality:  Calm / organic for reveals, precise for UI feedback (tokens in web/src/styles/tokens.css)
Signature moment:    The landing preview answer that streams in with its citation chip
Supporting layer:    One reveal system on the landing page; 120-280 ms hover/press/focus feedback
Stack:               CSS-native + Motion on the chat route, GSAP + Lenis on the landing page only
```

## The mark

A stethoscope chestpiece seen face-on (rim and diaphragm) whose rim resolves, at the lower left,
into a speech-bubble tail: listening first, then a conversation. It is drawn on a 32 x 32 grid in
`web/src/components/brand/mark-geometry.ts`, the single source shared by the React `<Mark>`
component and the brand build script.

- Regular drawing: rim 3 units wide, diaphragm radius 4.25. Use above 24 px.
- Small drawing (`small`): rim 3.75 units, diaphragm 4.75, so it survives 16 px rasterisation. Used for
  the favicon, the chat header and every rendering at 24 px or less.
- The tail always sits at the lower left, in every locale. It is part of the symbol, not a
  directional arrow, so it is never mirrored for Arabic.

## Wordmarks

| Script | Text | Typeface | Weight | Tracking |
|---|---|---|---|---|
| Latin | Ausculta | Atkinson Hyperlegible Next (Braille Institute, OFL) | 700 | -0.012 em |
| Arabic | أوسكولتا | Readex Pro (OFL) | 600 | 0 |

The wordmark SVGs are outlined (no font needed) by `web/scripts/brand/build-brand.mjs`, which shapes
the text with fontkit (so Arabic letters join correctly) and instantiates the variable fonts at the
weights above. Inside the app the wordmark is live text in the same fonts (`<Logo>`).

Lockups put the mark at the reading start: left of "Ausculta", right of "أوسكولتا". The mark is
1.3 times the height from the top of the letters to the baseline, centred on that band, with a
gap of 0.22 times the mark size.

## Files (`web/public/brand/`)

| File | Use |
|---|---|
| `ausculta-mark.svg` | Mark, spruce, for light backgrounds |
| `ausculta-mark-on-dark.svg` | Mark, mint, for dark backgrounds |
| `ausculta-mark-mono-black.svg` / `-mono-white.svg` | One-colour mark (print, stamps, embossing, photos) |
| `ausculta-wordmark-latin[-on-dark\|-mono-black\|-mono-white].svg` | Latin wordmark |
| `ausculta-wordmark-arabic[-on-dark\|-mono-black\|-mono-white].svg` | Arabic wordmark |
| `ausculta-lockup-latin[...].svg`, `ausculta-lockup-arabic[...].svg` | Mark + wordmark, same four variants |
| `ausculta-favicon.svg` | Browser tab icon; switches to mint in dark browser chrome (`prefers-color-scheme`) |
| `../favicon.ico` | 16, 32 and 48 px PNG-in-ICO for browsers and shortcuts that ask for `/favicon.ico` |
| `ausculta-app-icon.svg`, `-180.png`, `-192.png`, `-512.png` | Apple touch icon and web-app icons (full-bleed spruce square) |
| `ausculta-app-icon-maskable-512.png` | Maskable icon: the mark stays inside the 80% safe circle |
| `ausculta-og.svg` / `ausculta-og.png` | 1200 x 630 Open Graph / social card |

Regenerate everything after changing the geometry, the fonts or the colour tokens:

```
cd web
npm run brand
```

## Palette

All colours are OKLCH in `web/src/styles/tokens.css`, one `light-dark()` definition per token.
Brand hue is 165 (spruce); safety red (hue 27) is reserved for emergency and crisis UI only.
Ratios below are WCAG 2.2 contrast, measured by `npm run contrast` (18/18 pairs pass).

| Token | Light | Dark |
|---|---|---|
| `--bg` | `oklch(0.985 0.004 165)` #f8fbf9 | `oklch(0.17 0.012 170)` #0a110f |
| `--surface` | `oklch(1 0 0)` #ffffff | `oklch(0.21 0.014 170)` #121a17 |
| `--surface-2` | `oklch(0.962 0.01 165)` #edf5f1 | `oklch(0.245 0.016 170)` #19231f |
| `--line` | `oklch(0.89 0.012 165)` #d4ddd9 | `oklch(0.34 0.016 170)` #303b37 |
| `--line-strong` | `oklch(0.62 0.02 165)` #7c8a83 | `oklch(0.56 0.02 165)` #6a7871 |
| `--ink` | `oklch(0.22 0.02 170)` #111e19 | `oklch(0.95 0.008 165)` #eaf0ed |
| `--ink-2` | `oklch(0.44 0.02 170)` #485651 | `oklch(0.79 0.014 165)` #b3beb8 |
| `--brand` | `oklch(0.43 0.085 165)` #0e5e44 | `oklch(0.8 0.09 165)` #84d1af |
| `--brand-strong` | `oklch(0.36 0.075 165)` #014933 | `oklch(0.87 0.08 165)` #a2e6c7 |
| `--brand-soft` | `oklch(0.94 0.032 165)` #d8f2e6 | `oklch(0.3 0.045 165)` #153528 |
| `--brand-ink` | `oklch(0.36 0.075 165)` #014933 | `oklch(0.86 0.08 165)` #9fe2c4 |
| `--on-brand` | `oklch(0.99 0.004 165)` #f9fdfb | `oklch(0.17 0.02 170)` #06120e |
| `--danger` | `oklch(0.5 0.19 27)` #b7191c | `oklch(0.74 0.15 27)` #fb8276 |
| `--danger-soft` | `oklch(0.965 0.022 27)` #ffeeec | `oklch(0.27 0.06 27)` #3f1916 |
| `--danger-ink` | `oklch(0.42 0.16 27)` #901114 | `oklch(0.88 0.07 27)` #ffc7bf |
| `--on-danger` | `oklch(0.99 0.005 27)` #fffbfa | `oklch(0.17 0.03 27)` #1b0a08 |
| `--warn-soft` | `oklch(0.955 0.045 85)` #feefcf | `oklch(0.29 0.045 80)` #37290f |
| `--warn-ink` | `oklch(0.4 0.08 65)` #653d10 | `oklch(0.9 0.08 85)` #f7dba1 |
| `--focus` | `oklch(0.45 0.13 250)` #00579a | `oklch(0.8 0.11 250)` #86c3ff |

### Measured contrast

| Foreground | Background | Use | Light | Dark | Minimum |
|---|---|---|---|---|---|
| `--ink` | `--bg` | Body text | 16.51:1 | 16.53:1 | 4.5:1 |
| `--ink` | `--surface` | Body text on cards | 17.21:1 | 15.30:1 | 4.5:1 |
| `--ink-2` | `--bg` | Secondary text | 7.37:1 | 9.93:1 | 4.5:1 |
| `--ink-2` | `--surface` | Secondary text on cards | 7.68:1 | 9.18:1 | 4.5:1 |
| `--ink-2` | `--surface-2` | Secondary text on tinted bands | 6.91:1 | 8.40:1 | 4.5:1 |
| `--brand` | `--bg` | Links, brand text, the mark | 7.44:1 | 10.61:1 | 4.5:1 |
| `--brand` | `--surface` | Links on cards | 7.75:1 | 9.81:1 | 4.5:1 |
| `--brand` | `--surface-2` | Links on tinted bands | 6.97:1 | 8.97:1 | 4.5:1 |
| `--on-brand` | `--brand` | Primary button label, app icon | 7.54:1 | 10.59:1 | 4.5:1 |
| `--brand-ink` | `--brand-soft` | Citation chip | 8.88:1 | 9.02:1 | 4.5:1 |
| `--danger-ink` | `--danger-soft` | Emergency banner text | 8.19:1 | 10.36:1 | 4.5:1 |
| `--on-danger` | `--danger` | Emergency call button | 6.42:1 | 7.83:1 | 4.5:1 |
| `--warn-ink` | `--warn-soft` | Demo and notice text | 8.24:1 | 10.49:1 | 4.5:1 |
| `--focus` | `--bg` | Focus ring | 7.13:1 | 10.24:1 | 3:1 |
| `--focus` | `--surface` | Focus ring on cards | 7.43:1 | 9.47:1 | 3:1 |
| `--line-strong` | `--bg` | Input borders (non-text UI) | 3.46:1 | 4.14:1 | 3:1 |
| `--line-strong` | `--surface` | Input borders on cards | 3.61:1 | 3.83:1 | 3:1 |
| `--danger` | `--bg` | Emergency border and icon | 6.35:1 | 7.77:1 | 3:1 |

Social card (`ausculta-og.png`, background `oklch(0.3 0.06 168)` #013728): white wordmark 13.30:1,
tagline `oklch(0.9 0.025 165)` #d0e4da 10.00:1, mint mark and language line 7.43:1.

## Typography

| Role | Family | Notes |
|---|---|---|
| Latin text (EN, FR) | Atkinson Hyperlegible Next, variable 200-800 | Designed for low-vision readers; distinct I/l/1 and O/0 |
| Arabic text | Readex Pro, variable 160-700 | Arabic drawn for readability, humanist rhythm close to Atkinson |
| Fallbacks | ui-sans-serif, system-ui, Segoe UI, Tahoma, Arial | Per-glyph fallback: Latin always uses Atkinson, Arabic always Readex Pro |

- Fonts are self-hosted through `next/font/local` (no request to any third party; the CSP allows `font-src 'self'` only).
- Body text 17 px (1.0625 rem) at line-height 1.6; Arabic keeps the same size, never smaller.
- Headings 700, body 400, labels and buttons 600-700. No italics in Arabic.
- Numbers in phone links are always set left-to-right (`dir="ltr"`), even in Arabic.

## Logo usage

Clear space: keep at least the diaphragm's diameter (about a quarter of the mark) free on every side
of the mark or lockup. Minimum sizes: mark 16 px (small drawing), lockup 96 px wide on screen, 20 mm in print.

**Do**

- Use the spruce mark on light backgrounds and the mint `-on-dark` files on dark ones.
- Use the mono files on photos, in one-colour print, or wherever colour is not under your control.
- Use the Arabic lockup on Arabic pages and materials; the mark sits on the right.
- Keep the AI disclosure ("AI assistant") next to the logo inside the chat chrome.

**Don't**

- Don't mirror, rotate, outline, add a shadow or gradient to the mark, or change its proportions.
- Don't draw the mark in safety red, or use red anywhere in the brand outside emergency UI.
- Don't set the wordmark in another typeface, or retype it instead of using the outlined files.
- Don't place the spruce mark on mid-tone or busy backgrounds where it falls below 3:1.
- Don't combine the logo with a red cross, a caduceus, a heartbeat line or any sign that suggests
  an emergency service or a medical device. Ausculta is health information, not care.
