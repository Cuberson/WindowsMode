import SwiftUI

/// §5 — glass material: real Liquid Glass on macOS 26, `.ultraThinMaterial` before.
/// One shadow (hairline first), 20-pt continuous radius, no borders.
struct GlassBackground: ViewModifier {
    var radius: CGFloat = 20
    var interactive = false
    func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            content
                .glassEffect(interactive ? .regular.interactive() : .regular, in: .rect(cornerRadius: radius, style: .continuous))
                .shadow(color: .black.opacity(0.05), radius: 0, y: 0.5)
                .shadow(color: .black.opacity(0.18), radius: 24, y: 10)
        } else {
            content
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .strokeBorder(LinearGradient(colors: [.white.opacity(0.45), .white.opacity(0.05)], startPoint: .top, endPoint: .bottom), lineWidth: 0.5)
                )
                .shadow(color: .black.opacity(0.05), radius: 0, y: 0.5)
                .shadow(color: .black.opacity(0.18), radius: 24, y: 10)
        }
    }
}

extension View {
    func glass(radius: CGFloat = 20, interactive: Bool = false) -> some View { modifier(GlassBackground(radius: radius, interactive: interactive)) }
}

enum Motion {
    /// ~350 ms spring with a slight bounce (§5); collapses to a short ease when Reduce Motion is on.
    static var spring: Animation {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? .easeOut(duration: 0.15) : .spring(response: 0.35, dampingFraction: 0.78)
    }
}

struct StatusDot: View {
    let status: SessionStatus
    var body: some View {
        Circle().fill(color).frame(width: 8, height: 8)
            .animation(Motion.spring, value: status)
    }
    var color: Color {
        switch status {
        case .running: .accentColor
        case .done: .green
        case .needsInput: .orange
        case .failed: .red
        case .cancelled: .secondary
        }
    }
}

struct Chip: View {
    let text: String
    var tint: Color = .secondary
    var body: some View {
        Text(text).font(.system(size: 11, weight: .medium))
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(tint.opacity(0.14), in: Capsule())
            .foregroundStyle(tint)
    }
}
