import SwiftUI
import AppKit
import Carbon.HIToolbox

/// "Record shortcut" field: click, press a chord, it validates via Carbon before saving (§3.6).
struct ShortcutRecorder: View {
    @Binding var hotkey: Hotkey
    @State private var recording = false
    @State private var message: String?
    @State private var monitor: Any?

    var body: some View {
        HStack(spacing: 8) {
            Button {
                recording.toggle()
                if recording { beginRecording() } else { endRecording() }
            } label: {
                Text(recording ? "Press a chord…" : hotkey.display)
                    .font(.system(size: 13, weight: .medium)).monospaced()
                    .frame(minWidth: 110)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(Color.primary.opacity(recording ? 0.12 : 0.06), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            if let message { Text(message).font(.system(size: 11)).foregroundStyle(.red) }
        }
        .onDisappear { endRecording() }
    }

    private func beginRecording() {
        message = nil
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { e in
            let mods = Hotkey.carbonModifiers(e.modifierFlags)
            if e.keyCode == 53 { endRecording(); return nil } // esc cancels
            guard mods != 0 else { message = "Add at least one modifier (⌘ ⇧ ⌥ ⌃)"; return nil }
            let hk = Hotkey(keyCode: UInt32(e.keyCode), modifiers: mods)
            if HotkeyMonitor.shared.canRegister(hk) { hotkey = hk; message = nil }
            else { message = "\(hk.display) is taken by another app" }
            endRecording()
            return nil
        }
    }

    private func endRecording() {
        recording = false
        if let monitor { NSEvent.removeMonitor(monitor); self.monitor = nil }
    }
}
