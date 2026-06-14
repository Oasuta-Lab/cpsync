import Foundation

@MainActor
class AppConfig: ObservableObject {
    static let shared = AppConfig()

    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") }
    }

    @Published var roomName: String {
        didSet { UserDefaults.standard.set(roomName, forKey: "roomName") }
    }

    var wsURL: URL? {
        guard !serverURL.isEmpty, !roomName.isEmpty,
              let encoded = roomName.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed)
        else { return nil }
        return URL(string: "\(serverURL)?room=\(encoded)")
    }

    var isConfigured: Bool {
        !serverURL.isEmpty && !roomName.isEmpty
    }

    private init() {
        serverURL = UserDefaults.standard.string(forKey: "serverURL") ?? ""
        roomName = UserDefaults.standard.string(forKey: "roomName") ?? ""
    }
}
