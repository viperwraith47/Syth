# macOS App Requirements — Pure macOS Edition (Viperwraith47)

> **100% macOS-native — SwiftUI + AppKit. Upload to any AI coder and it will scaffold a macOS app with Apple Liquid Glass UI and Viperwraith47 credit.**

**Made by [Viperwraith47](https://github.com/viperwraith47)**

## What's Inside

- `AGENTS.md` — short agent rules (pure macOS, 4 MUSTs)
- `PROJECT_REQUIREMENTS.md` — full constitution (pure macOS, 4 MUSTs, templates, checklist)
- `macos-app-project-initializer.md` — same contract (alternate upload name)
- `AI init.md` — universal AI instructions for macOS (pure macOS)
- `SKILL.md` — Apple Liquid Glass skill for macOS (SwiftUI materials + spring physics)
- `build.sh` — executable build template (xcodebuild / SwiftPM)
- `src_template/` — copy-paste SwiftUI components

## The 4 MUSTs (Pure macOS)

### R1 — build.sh at repo root
- Builds via `xcodebuild` (workspace/project) and/or SwiftPM `swift build`
- Can run/open app via `open`
- Banner credits Viperwraith47 with `https://github.com/viperwraith47`
- Executable (`chmod +x build.sh`)

### R2 — GitHub-ready README.md
- Title, badges (macOS 14+, Swift 5.9+, Xcode 15+), features, requirements (macOS 14 Sonoma+, Xcode 15+, Apple Silicon/Intel)
- Build/run via `./build.sh`
- Project structure, license
- Credit: `Made by [Viperwraith47](https://github.com/viperwraith47)` with exact URL

### R3 — Apple Liquid Glass UI
- **Materials:** `.ultraThinMaterial` / `.thinMaterial` / `.regularMaterial` for panels/cards/toolbars
- **Corners:** `RoundedRectangle(cornerRadius: 20, style: .continuous)` / `Capsule(style: .continuous)`
- **Rim light:** 1px white gradient 55% → 5% via `strokeBorder(LinearGradient)`
- **Depth:** layered shadows `black 18% radius 24 y12` + `black 6% radius 2 y1` + inner highlight
- **Backdrop:** vibrant gradient / image / vibrant color behind glass so translucency obvious
- **Motion:** SwiftUI springs `response 0.35 dampingFraction 1.0` (no bounce), `response 0.3 dampingFraction 0.8` for momentum
- Applied to primary surfaces: main card, sidebars, inspector panels, key buttons — not flat gray only

### R4 — Viperwraith47 Credit
- Visible `Made by Viperwraith47` in app footer and README
- Click in app → opens default browser to `https://github.com/viperwraith47` via `NSWorkspace.shared.open(url)`
- Must have accessibilityLabel, hint, isLink trait, pointing hand cursor on hover
- URL exactly `https://github.com/viperwraith47`

## How to Use

1. Copy `AGENTS.md` + `PROJECT_REQUIREMENTS.md` to repo root
2. Tell AI:

```
Read AGENTS.md and PROJECT_REQUIREMENTS.md first. This is a macOS app (SwiftUI/SwiftPM).

You MUST include:
(1) root build.sh (xcodebuild/SwiftPM build + run + Viperwraith47 banner),
(2) GitHub-ready README.md with Made by [Viperwraith47](https://github.com/viperwraith47),
(3) Apple Liquid Glass UI (SwiftUI .ultraThinMaterial/.thinMaterial, continuous corners, rim light, depth) on primary surfaces over vibrant backdrop,
(4) visible Made by Viperwraith47 credit that opens https://github.com/viperwraith47 in default browser via NSWorkspace.shared.open.

Follow templates in PROJECT_REQUIREMENTS.md. Verify acceptance checklist.
```

3. `chmod +x build.sh && ./build.sh` → verify glass + credit

## Core Requirements Preserved

- **GitHub link:** `https://github.com/viperwraith47` — exact, clickable, opens default browser
- **Glass effects:** SwiftUI materials, continuous corners, rim light gradient, depth shadows, vibrant backdrop, spring motion
- **Credit:** visible footer + README + build.sh banner, accessible
- **Stack:** 100% macOS — Swift, SwiftUI, AppKit, xcodebuild, SwiftPM

---
Made by [Viperwraith47](https://github.com/viperwraith47)
