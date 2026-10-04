---
name: apple-design-macos
description: Apple's approach to interface design and fluid, physical motion for macOS. Use when building or reviewing SwiftUI gesture-driven UI, spring animations, drag/swipe/sheet interactions, momentum and interruptible transitions, translucent Liquid Glass materials (ultraThinMaterial/thinMaterial), depth, typography, and design foundations behind Apple-style macOS interfaces.
---

# Apple Design for macOS — Liquid Glass Edition

How Apple builds macOS interfaces that stop feeling like a computer and start feeling like an extension of you. Distilled from WWDC design talks — chiefly *Designing Fluid Interfaces* (WWDC 2018) — translated for macOS platform (SwiftUI, AppKit, `NSVisualEffectView`).

> This skill is REQUIRED for any macOS app that must implement Apple Liquid Glass UI per PROJECT_REQUIREMENTS.md R3.

## 1. Liquid Glass Material System (macOS)

Liquid Glass is not just translucency — it's layered material with depth, rim light, and backdrop visibility.

### Core SwiftUI recipe (pure macOS)

```swift
import SwiftUI

struct LiquidGlassBackground: View {
    var cornerRadius: CGFloat = 20
    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.ultraThinMaterial) // or .thinMaterial for buttons
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(0.55),
                                Color.white.opacity(0.12),
                                Color.white.opacity(0.05)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
            )
            .shadow(color: .black.opacity(0.18), radius: 24, x: 0, y: 12)
            .shadow(color: .black.opacity(0.06), radius: 2, x: 0, y: 1)
    }
}

extension View {
    func liquidGlass(cornerRadius: CGFloat = 16) -> some View {
        self.background { LiquidGlassBackground(cornerRadius: cornerRadius) }
    }
    func liquidGlassButton() -> some View {
        self
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background {
                Capsule(style: .continuous)
                    .fill(.thinMaterial)
                    .overlay(Capsule(style: .continuous).strokeBorder(Color.white.opacity(0.35), lineWidth: 1))
            }
    }
}
```

### Vibrant backdrop (required so translucency is visible)

```swift
ZStack {
    LinearGradient(colors: [Color(red: 0.15, green: 0.25, blue: 0.55), Color(red: 0.35, green: 0.15, blue: 0.45)], startPoint: .topLeading, endPoint: .bottomTrailing)
        .ignoresSafeArea()
    // Your glass cards over it
}
```

### Rules

- **Container Materials:** `.ultraThinMaterial` for main cards, `.thinMaterial` for buttons, `.regularMaterial` for sidebars/toolbars. Never flat `Color.gray` only.
- **Specular Highlights:** 1px inside border gradient top-left white 55% → bottom-right white 5% — mimics light catching edge.
- **Fluid Elements:** Active controls use vibrant gradients + inner glow.
- **Translucency:** Material handles translucency automatically — ensure backdrop is vibrant (gradient/image) not plain gray, so effect is obvious.
- **Depth:** Layered shadows `black 18% radius 24 y12` + `black 6% radius 2 y1` + inner highlight.
- **Continuous Corners:** `RoundedRectangle(cornerRadius: 20, style: .continuous)` / `Capsule(style: .continuous)` — not sharp or circular only.
- **Bigger surfaces = thicker:** stronger material + deeper shadow than small chips.
- **Never stack light translucent on light translucent** — legibility collapses.
- **Vibrant backdrop required:** gradient mesh, image, or saturated color behind glass.

| Surface | Material | Shadow | Radius |
|---------|----------|--------|--------|
| Page background | vibrant gradient | — | — |
| Main card | ultraThinMaterial | 12/24 + 1/2 | 20-24px continuous |
| Sidebar / toolbar | regularMaterial | subtle | 0 or 16px continuous |
| Button | thinMaterial | 4/12 | capsule continuous |
| Chip / badge | thinMaterial | 2/8 | 12px continuous |

## 2. Response — kill latency (macOS)

- Respond on mouse-down, not mouse-up. Highlight button instantly on press.
- Audit debounces, artificial timers.
- Feedback must be continuous during drag, not just at end.

## 3. Direct manipulation — 1:1 tracking (macOS)

- Use SwiftUI `DragGesture` with `minimumDistance` threshold (~10pt) for hysteresis.
- Respect grab offset — don't snap to center on grab.
- Track velocity for momentum.

## 4. Interruptibility — most important

- Never lock out input during transition.
- Always animate from presentation (current) value, not target.
- Avoid fixed-duration animations for gesture-driven UI — use springs that re-target from current value.
- When reversing, blend velocity — don't hard-cut.

## 5. Behavior over animation — use springs (macOS)

- **Damping fraction:** `1.0` = critically damped, no bounce. `<1.0` = bouncy.
- **Response:** how quickly reaches target — not duration.

**Defaults:**
- Most UI: `dampingFraction 1.0, response 0.35` (no overshoot)
- Momentum / drawer: `dampingFraction 0.8, response 0.3` (slight bounce when gesture had momentum)

```swift
// Critically damped default
.animation(.spring(response: 0.35, dampingFraction: 1.0), value: isExpanded)

// Momentum
.animation(.spring(response: 0.3, dampingFraction: 0.8), value: offset)
```

| Interaction | Damping | Response |
|-------------|---------|----------|
| Move / reposition | 1.0 | 0.4 |
| Rotation | 0.8 | 0.4 |
| Drawer / sheet | 0.8 | 0.3 |

## 6. Velocity handoff (macOS)

Pass release velocity as spring's initial velocity so no seam between drag and animation. SwiftUI `DragGesture` provides `velocity`.

## 7. Momentum projection (macOS)

Project resting position from velocity, then snap to nearest target — makes flick feel like throw.

## 8. Spatial consistency (macOS)

- Enter and exit along same path.
- Anchor popovers/sheets to trigger.
- Mirror easing on reversible transitions.

## 9. Rubber-banding — soft boundaries (macOS)

Progressive resistance at edges, not hard stop.

## 10. Materials & depth — macOS specifics

- Build nav/toolbars/sheets as translucent layers with `NSVisualEffectView` / materials, content scrolling underneath — not opaque bars.
- Material weight encodes hierarchy: heavier = structural (sidebars), lighter = interactive (buttons).
- Dim to focus, separate to keep flow: modal = dimming + push back; parallel panel = translucency without scrim.
- For stacked sheets, progressively dim and push back parent layers.
- Scroll edge effects, not hard dividers: fade blur/gradient mask where content meets chrome.
- Materialize, don't just fade: animate material + scale together on enter/exit.

## 11. Typography (macOS)

- Tracking size-specific: large display negative, body near 0.
- Leading inverse to size: tight on headings, looser on body.
- Build hierarchy from weight + size + leading, not size alone.
- Respect user's text size — use Dynamic Type where possible.
- Default to system font: `.system` before custom.

## 12. Reduced motion & transparency (macOS)

SwiftUI respects system settings automatically for materials, but:

- Replace slides/springs with opacity cross-fades when `accessibilityReduceMotion` is enabled.
- Materials automatically become more opaque when `accessibilityReduceTransparency` is enabled.
- Avoid full-window moving backgrounds, 0.2Hz oscillations.

```swift
@Environment(\.accessibilityReduceMotion) var reduceMotion
@Environment(\.accessibilityReduceTransparency) var reduceTransparency
```

## 13. Quick Reference (macOS)

| Need | Technique | Value |
|------|-----------|-------|
| Default spring | Critically damped | dampingFraction 1.0, response 0.35 |
| Flick spring | Under-damped | dampingFraction 0.8, response 0.3 |
| Glass material | Translucent | ultraThinMaterial / thinMaterial |
| Rim light | Gradient border | white 55% → 5% |
| Corner | Continuous | 20-24px, style: .continuous |
| Depth | Layered shadow | 0 12/24 18% + 0 1/2 6% |
| Backdrop | Vibrant gradient | blue → purple mesh |
| Interrupt | Start from live value | read presentation value |

## 14. Design foundations (8 principles for macOS)

1. **Purpose** — intentional, what NOT to build
2. **Agency** — choices, easy undo, confirm only destructive
3. **Responsibility** — privacy at right moment, anticipate harm
4. **Familiarity** — metaphors, consistency, predictable, close always top-left on macOS
5. **Flexibility** — adapt to device, abilities, personalize
6. **Simplicity** — strip unnecessary, hierarchy via spacing/contrast, common path first
7. **Craft** — deliberate spacing/timing/alignment, no jitter
8. **Delight** — emotion from getting other 7 right

---

Use this skill whenever building Liquid Glass UI for macOS, SwiftUI gesture interactions, spring animations, or reviewing macOS interfaces.
Pure macOS — uses SwiftUI materials, `NSWorkspace`, xcodebuild/SwiftPM, no web dependencies.
