import SwiftUI

@main
struct CpSyncApp: App {
    @StateObject private var syncManager = SyncManager()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(syncManager)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                // Reconnect if needed (e.g. after a crash / first launch)
                syncManager.connect()
            }
            // .background → do nothing: silent audio keeps the app alive
            // and the WebSocket + clipboard monitor keep running.
        }
    }
}
