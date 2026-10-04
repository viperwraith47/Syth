import SwiftUI
import AppKit

/// Project credit. Clicking opens https://github.com/viperwraith47 in the default browser.
/// Made by Viperwraith47 — https://github.com/viperwraith47
/// REQUIRED by PROJECT_REQUIREMENTS.md R4
struct ViperwraithCreditView: View {
    private let profileURL = URL(string: "https://github.com/viperwraith47")!

    var body: some View {
        HStack(spacing: 6) {
            Text("Made by")
                .font(.caption)
                .foregroundStyle(.secondary)

            Button {
                openGitHubProfile()
            } label: {
                Text("Viperwraith47")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                    .underline()
            }
            .buttonStyle(.plain)
            .help("Open https://github.com/viperwraith47")
            .onHover { hovering in
                if hovering {
                    NSCursor.pointingHand.push()
                } else {
                    NSCursor.pop()
                }
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Made by Viperwraith47")
        .accessibilityHint("Opens GitHub profile in your browser")
        .accessibilityAddTraits(.isLink)
    }

    private func openGitHubProfile() {
        NSWorkspace.shared.open(profileURL)
    }
}
