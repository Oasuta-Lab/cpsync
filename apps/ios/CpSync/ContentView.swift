import SwiftUI

struct ContentView: View {
    @EnvironmentObject var sync: SyncManager
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    StatusCard()
                    ActionButtons()
                    HistorySection()
                }
                .padding()
            }
            .navigationTitle("Clipboard Sync")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: {
                        Image(systemName: "gear")
                    }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .onAppear {
                if !AppConfig.shared.isConfigured {
                    showSettings = true
                }
            }
        }
    }
}

// MARK: - Status card

struct StatusCard: View {
    @EnvironmentObject var sync: SyncManager

    var body: some View {
        HStack(spacing: 20) {
            ZStack {
                Circle()
                    .fill(sync.isConnected ? Color.green.opacity(0.15) : Color.red.opacity(0.15))
                    .frame(width: 56, height: 56)
                Image(systemName: sync.isConnected ? "wifi" : "wifi.slash")
                    .font(.title2)
                    .foregroundStyle(sync.isConnected ? .green : .red)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(sync.isConnected ? "Connected" : "Disconnected")
                    .font(.title3.bold())
                Text(sync.statusMessage)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
        }
        .padding(20)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}

// MARK: - Action buttons

struct ActionButtons: View {
    @EnvironmentObject var sync: SyncManager

    var body: some View {
        HStack(spacing: 12) {
            Button {
                sync.isConnected ? sync.disconnect() : sync.connect()
            } label: {
                Label(
                    sync.isConnected ? "Disconnect" : "Connect",
                    systemImage: sync.isConnected ? "wifi.slash" : "wifi"
                )
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
            }
            .buttonStyle(.bordered)
            .tint(sync.isConnected ? .red : .green)
            .controlSize(.large)

            Button { sync.sendCurrentClipboard() } label: {
                Label("Send Clipboard", systemImage: "doc.on.clipboard")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 4)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .disabled(!sync.isConnected)
        }
    }
}

// MARK: - History

struct HistorySection: View {
    @EnvironmentObject var sync: SyncManager

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Sync History")
                    .font(.headline)
                Spacer()
                if !sync.history.isEmpty {
                    Button("Clear") { sync.clearHistory() }
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            if sync.history.isEmpty {
                ContentUnavailableView(
                    "No syncs yet",
                    systemImage: "doc.on.clipboard",
                    description: Text("Clipboard changes while connected appear here")
                )
                .padding(.vertical, 40)
            } else {
                LazyVStack(spacing: 8) {
                    ForEach(sync.history) { entry in
                        HistoryRow(entry: entry)
                    }
                }
            }
        }
    }
}

struct HistoryRow: View {
    let entry: SyncEntry

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: entry.direction == .sent
                  ? "arrow.up.circle.fill"
                  : "arrow.down.circle.fill")
                .foregroundStyle(entry.direction == .sent ? .blue : .orange)
                .font(.title3)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 4) {
                Text(entry.text)
                    .lineLimit(3)
                Text(entry.timestamp.formatted(date: .omitted, time: .standard))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(12)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
    }
}

// MARK: - Settings

struct SettingsView: View {
    @ObservedObject var config = AppConfig.shared
    @EnvironmentObject var sync: SyncManager
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("WebSocket URL", text: $config.serverURL)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }
                Section("Room") {
                    TextField("Room name / secret key", text: $config.roomName)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }
                Section {
                    LabeledContent("Full URL") {
                        Text(config.wsURL?.absoluteString ?? "Invalid URL")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.trailing)
                    }
                }
                Section {
                    Button("Reconnect with new settings") {
                        sync.disconnect()
                        sync.connect()
                        dismiss()
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(SyncManager())
}
