import SwiftUI

enum PillState: Equatable { case listening, thinking, speaking, clarify, error }

@MainActor @Observable
final class PillModel {
    var state: PillState = .listening
    var transcript = ""
    var secondary = ""       // clarify question / error text
    var level: Float = 0
    var fallbackBadge = false
    var visible = false
}

/// §5.1 — 320 pt wide pill; transcript wraps to max 3 lines, newest words kept visible.
struct ListeningPillView: View {
    @Bindable var model: PillModel

    var body: some View {
        if model.visible { content } else { Color.clear.frame(width: 320, height: 56) }
    }

    private var content: some View {
        HStack(spacing: 12) {
            leading
            VStack(alignment: .leading, spacing: 2) {
                Text(primaryText)
                    .font(.system(size: 15, weight: .medium))
                    .lineLimit(3)
                    .truncationMode(.head)
                    .foregroundStyle(model.transcript.isEmpty && model.state == .listening ? .secondary : .primary)
                    .fixedSize(horizontal: false, vertical: true)
                if !model.secondary.isEmpty {
                    Text(model.secondary)
                        .font(.system(size: 12))
                        .foregroundStyle(model.state == .error ? Color.red : Color.secondary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
            trailing
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .frame(width: 320, alignment: .leading)
        .frame(minHeight: 56)
        .glass(radius: 28)
        .animation(Motion.spring, value: model.state)
    }

    private var primaryText: String {
        switch model.state {
        case .listening: model.transcript.isEmpty ? "Listening…" : model.transcript
        case .thinking: model.transcript.isEmpty ? "Thinking…" : model.transcript
        case .speaking, .clarify, .error: model.transcript
        }
    }

    @ViewBuilder private var leading: some View {
        switch model.state {
        case .listening:
            Circle().fill(Color.accentColor)
                .frame(width: 12, height: 12)
                .scaleEffect(1 + CGFloat(model.level) * 0.9)
                .animation(.easeOut(duration: 0.08), value: model.level)
        case .thinking:
            ThinkingDots()
        case .speaking:
            MiniWaveform()
        case .clarify:
            Image(systemName: "questionmark.circle.fill").foregroundStyle(Color.accentColor).font(.system(size: 14))
        case .error:
            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.red).font(.system(size: 14))
        }
    }

    @ViewBuilder private var trailing: some View {
        if model.fallbackBadge {
            Image(systemName: "speaker.wave.1").font(.system(size: 11)).foregroundStyle(.tertiary).help("Using system voice")
        } else {
            switch model.state {
            case .listening: Image(systemName: "mic.fill").font(.system(size: 12)).foregroundStyle(.secondary)
            case .thinking: EmptyView()
            case .speaking: Image(systemName: "speaker.wave.2.fill").font(.system(size: 12)).foregroundStyle(.secondary)
            case .clarify: Image(systemName: "arrow.turn.down.left").font(.system(size: 12)).foregroundStyle(.secondary)
            case .error: EmptyView()
            }
        }
    }
}

struct ThinkingDots: View {
    @State private var on = false
    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<3) { i in
                Circle().fill(Color.accentColor).frame(width: 4, height: 4)
                    .opacity(on ? 1 : 0.3)
                    .animation(.easeInOut(duration: 0.45).repeatForever(autoreverses: true).delay(Double(i) * 0.15), value: on)
            }
        }
        .frame(width: 12)
        .onAppear { on = true }
    }
}

struct MiniWaveform: View {
    @State private var on = false
    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<4) { i in
                Capsule().fill(Color.accentColor).frame(width: 2, height: on ? 12 : 4)
                    .animation(.easeInOut(duration: 0.3 + Double(i) * 0.07).repeatForever(autoreverses: true), value: on)
            }
        }
        .frame(width: 12, height: 14)
        .onAppear { on = true }
    }
}
