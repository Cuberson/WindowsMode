import SwiftUI

/// §5.2 — 360-pt glass board of session cards. Draggable via the panel's movableByWindowBackground.
struct SessionsOverlayView: View {
    let store: SessionStore
    let chordText: String
    let onClose: () -> Void
    let onOpen: (Session) -> Void
    let onLog: (Session) -> Void
    let onReply: (Session, String) -> Void
    let onStop: (Session) -> Void
    let onDismiss: (Session) -> Void
    @State private var now = Date()
    @State private var contentHeight: CGFloat = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            if store.visible.isEmpty {
                Text("Hold \(chordText) and say what you need.")
                    .font(.system(size: 13))
                    .foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 12)
            } else {
                ScrollView(showsIndicators: false) {
                    VStack(spacing: 8) {
                        ForEach(store.visible) { s in
                            SessionCard(session: s, now: now,
                                        onOpen: { onOpen(s) }, onLog: { onLog(s) }, onReply: { onReply(s, $0) },
                                        onStop: { onStop(s) }, onDismiss: { onDismiss(s) })
                            .transition(.move(edge: .top).combined(with: .opacity))
                        }
                    }
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { contentHeight = $0 }
                }
                .frame(height: min(max(contentHeight, 40), 560 - 56))
            }
        }
        .padding(12)
        .frame(width: 360)
        .frame(minHeight: 88)
        .glass(radius: 20)
        .animation(Motion.spring, value: store.visible.map(\.id))
        .task {
            // One tick per second only while something is running — elapsed labels; otherwise idle.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                if !store.running.isEmpty || store.visible.contains(where: { ($0.finishedAt.map { now.timeIntervalSince($0) } ?? 0) < 660 }) { now = Date() }
            }
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Text("Sessions").font(.system(size: 13, weight: .semibold)).foregroundStyle(.secondary)
            if !store.running.isEmpty {
                Text("\(store.running.count)").font(.system(size: 11, weight: .semibold))
                    .padding(.horizontal, 6).padding(.vertical, 1)
                    .background(Color.accentColor.opacity(0.15), in: Capsule())
                    .foregroundStyle(Color.accentColor)
            }
            Spacer()
            Button(action: onClose) {
                Image(systemName: "xmark").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                    .frame(width: 22, height: 22).contentShape(Rectangle())
            }.buttonStyle(.plain)
        }
        .padding(.horizontal, 4)
    }
}

struct SessionCard: View {
    let session: Session
    let now: Date
    let onOpen: () -> Void
    let onLog: () -> Void
    let onReply: (String) -> Void
    let onStop: () -> Void
    let onDismiss: () -> Void
    @State private var hover = false
    @State private var replying = false
    @State private var reply = ""

    private var collapsed: Bool {
        guard let f = session.finishedAt else { return false }
        return now.timeIntervalSince(f) > 600
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                StatusDot(status: session.status)
                Text(session.projectName).font(.system(size: 15, weight: .semibold)).lineLimit(1)
                HStack(spacing: 4) {
                    AgentIcon(agent: session.agent, size: 13)
                    Text(session.agent.displayName).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                }
                .padding(.horizontal, 7).padding(.vertical, 2)
                .background(Color.secondary.opacity(0.12), in: Capsule())
                .help(session.agent.displayName)
                Spacer()
                Text(timeLabel).font(.system(size: 11)).foregroundStyle(.tertiary).monospacedDigit()
            }
            if !collapsed {
                Text(session.task).font(.system(size: 13)).foregroundStyle(.secondary).lineLimit(2)
                if session.status == .running && !session.activity.isEmpty {
                    Text(session.activity).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary).lineLimit(1)
                }
                if session.status == .needsInput {
                    Text("Needs input — open it and continue with --resume").font(.system(size: 11)).foregroundStyle(.orange)
                }
                if replying {
                    TextField("Follow-up…", text: $reply)
                        .textFieldStyle(.roundedBorder).font(.system(size: 12))
                        .onSubmit { let t = reply; reply = ""; replying = false; if !t.isEmpty { onReply(t) } }
                        .onExitCommand { replying = false }
                }
            }
            if hover {
                HStack(spacing: 6) {
                    action("terminal", "Open", onOpen)
                    action("doc.text", "Show log", onLog)
                    if session.status == .running || session.agentSessionID != nil {
                        action("arrowshape.turn.up.left", "Reply") { replying.toggle() }
                    }
                    if session.status == .running { action("stop.fill", "Stop", onStop) }
                    else { action("xmark.circle", "Dismiss", onDismiss) }
                    Spacer()
                }
                .transition(.opacity)
            }
        }
        .padding(12)
        .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(alignment: .bottom) { if session.status == .running { ProgressShimmer().padding(.horizontal, 14) } }
        .onHover { hover = $0 }
        .animation(Motion.spring, value: hover)
        .animation(Motion.spring, value: replying)
    }

    private func action(_ symbol: String, _ label: String, _ act: @escaping () -> Void) -> some View {
        Button(action: act) {
            Label(label, systemImage: symbol).labelStyle(.iconOnly).font(.system(size: 11, weight: .medium))
                .frame(width: 24, height: 20).contentShape(Rectangle())
        }
        .buttonStyle(.plain).foregroundStyle(.secondary).help(label)
    }

    private var timeLabel: String {
        if session.status == .running { return SessionStore.format(now.timeIntervalSince(session.startedAt)) }
        guard let f = session.finishedAt else { return "" }
        let ago = now.timeIntervalSince(f)
        return ago < 60 ? "just now" : "\(SessionStore.format(ago)) ago"
    }
}

/// 1-pt shimmer along the bottom edge of a running card.
struct ProgressShimmer: View {
    @State private var on = false
    var body: some View {
        GeometryReader { g in
            Capsule().fill(LinearGradient(colors: [.clear, Color.accentColor.opacity(0.7), .clear], startPoint: .leading, endPoint: .trailing))
                .frame(width: g.size.width * 0.4, height: 1)
                .offset(x: (on ? 1 : -0.4) * g.size.width)
                .animation(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? nil : .linear(duration: 1.6).repeatForever(autoreverses: false), value: on)
                .onAppear { on = true }
        }
        .frame(height: 1)
    }
}
