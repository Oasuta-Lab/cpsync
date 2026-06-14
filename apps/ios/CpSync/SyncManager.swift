import Foundation
import UIKit

enum SyncDirection { case sent, received }

struct SyncEntry: Identifiable {
    let id = UUID()
    let text: String
    let direction: SyncDirection
    let timestamp = Date()
}

@MainActor
class SyncManager: ObservableObject {
    @Published var isConnected = false
    @Published var history: [SyncEntry] = []
    @Published var statusMessage = "Not connected"

    let config = AppConfig.shared

    private var webSocketTask: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var clipboardTask: Task<Void, Never>?
    private var pingTask: Task<Void, Never>?
    private var lastChangeCount = UIPasteboard.general.changeCount
    private var suppressNextChange = false

    func connect() {
        guard let url = config.wsURL else {
            statusMessage = "Invalid server URL — check Settings"
            return
        }
        guard !isConnected else { return }

        cancelAllTasks()

        let task = URLSession.shared.webSocketTask(with: url)
        task.resume()
        webSocketTask = task

        isConnected = true
        statusMessage = "Connected — room: \(config.roomName)"

        BackgroundAudioKeepAlive.shared.start()
        startReceiveLoop()
        startClipboardMonitor()
        startPingLoop()
    }

    func disconnect() {
        cancelAllTasks()
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        BackgroundAudioKeepAlive.shared.stop()
        isConnected = false
        statusMessage = "Disconnected"
    }

    func sendCurrentClipboard() {
        guard let text = UIPasteboard.general.string, !text.isEmpty else { return }
        send(text)
    }

    func clearHistory() {
        history.removeAll()
    }

    // MARK: - Private

    private func send(_ text: String) {
        guard let task = webSocketTask else { return }
        task.send(.string(text)) { [weak self] error in
            Task { @MainActor [weak self] in
                if let error {
                    self?.statusMessage = "Send failed: \(error.localizedDescription)"
                } else {
                    self?.addEntry(SyncEntry(text: text, direction: .sent))
                }
            }
        }
    }

    private func startReceiveLoop() {
        receiveTask = Task {
            while !Task.isCancelled, let task = webSocketTask {
                do {
                    let msg = try await task.receive()
                    if case .string(let text) = msg, !text.isEmpty {
                        suppressNextChange = true
                        UIPasteboard.general.string = text
                        lastChangeCount = UIPasteboard.general.changeCount
                        suppressNextChange = false
                        addEntry(SyncEntry(text: text, direction: .received))
                    }
                } catch {
                    guard !Task.isCancelled else { return }
                    handleConnectionLost(error)
                    return
                }
            }
        }
    }

    private func startClipboardMonitor() {
        lastChangeCount = UIPasteboard.general.changeCount
        clipboardTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled, !suppressNextChange else { continue }
                let current = UIPasteboard.general.changeCount
                if current != lastChangeCount {
                    lastChangeCount = current
                    if let text = UIPasteboard.general.string, !text.isEmpty {
                        send(text)
                    }
                }
            }
        }
    }

    private func startPingLoop() {
        pingTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                guard !Task.isCancelled else { return }
                webSocketTask?.sendPing { _ in }
            }
        }
    }

    private func handleConnectionLost(_ error: Error) {
        cancelAllTasks()
        webSocketTask = nil
        isConnected = false
        statusMessage = "Reconnecting in 5 s…"

        Task {
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled else { return }
            connect()
        }
    }

    private func cancelAllTasks() {
        receiveTask?.cancel(); receiveTask = nil
        clipboardTask?.cancel(); clipboardTask = nil
        pingTask?.cancel(); pingTask = nil
    }

    private func addEntry(_ entry: SyncEntry) {
        history.insert(entry, at: 0)
        if history.count > 50 { history.removeLast() }
    }
}
