import SwiftUI

/// Apple-style Liquid Glass backdrop for macOS windows/panels.
/// Made by Viperwraith47 — https://github.com/viperwraith47
struct LiquidGlassBackground: View {
    var cornerRadius: CGFloat = 20

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.ultraThinMaterial)
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
