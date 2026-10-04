import SwiftUI

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
