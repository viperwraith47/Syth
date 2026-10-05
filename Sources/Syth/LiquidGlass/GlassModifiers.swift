import SwiftUI

/// Glass modifier extensions — applies Liquid Glass card chrome (material + rim light + depth).
/// Swift reference implementation — the Python equivalent is in glass_ui.py GlassPanel.
/// Made by Viperwraith47 — https://github.com/viperwraith47
extension View {
    /// Apply Liquid Glass card chrome (material + rim light + depth).
    func liquidGlass(cornerRadius: CGFloat = 16) -> some View {
        self.background {
            LiquidGlassBackground(cornerRadius: cornerRadius)
        }
    }

    /// Soft glass button style for primary actions.
    func liquidGlassButton() -> some View {
        self
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background {
                Capsule(style: .continuous)
                    .fill(.thinMaterial)
                    .overlay(
                        Capsule(style: .continuous)
                            .strokeBorder(Color.white.opacity(0.35), lineWidth: 1)
                    )
            }
    }
}
