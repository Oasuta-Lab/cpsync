import AVFoundation

/// Plays a completely silent audio graph via AVAudioEngine.
/// This keeps the app alive in the background (requires UIBackgroundModes = audio
/// in Info.plist), allowing the clipboard monitor and WebSocket to keep running
/// even when the user switches away from the app.
@MainActor
final class BackgroundAudioKeepAlive {
    static let shared = BackgroundAudioKeepAlive()

    private var engine: AVAudioEngine?
    private(set) var isRunning = false

    private init() {
        // Restart the engine automatically after an audio interruption (e.g. phone call)
        NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            Task { @MainActor [weak self] in
                self?.handleInterruption(notification)
            }
        }
    }

    func start() {
        guard !isRunning else { return }
        do {
            let session = AVAudioSession.sharedInstance()
            // .mixWithOthers so we don't interrupt music / podcasts the user has playing
            try session.setCategory(.playback, mode: .default, options: .mixWithOthers)
            try session.setActive(true)

            let engine = AVAudioEngine()
            let mixer = engine.mainMixerNode
            let output = engine.outputNode
            engine.connect(mixer, to: output, format: output.inputFormat(forBus: 0))
            mixer.outputVolume = 0.0   // completely silent — no audio is produced

            try engine.start()
            self.engine = engine
            isRunning = true
        } catch {
            print("[BackgroundAudio] start failed: \(error)")
        }
    }

    func stop() {
        engine?.stop()
        engine = nil
        isRunning = false
        try? AVAudioSession.sharedInstance().setActive(
            false, options: .notifyOthersOnDeactivation
        )
    }

    // MARK: - Private

    private func handleInterruption(_ notification: Notification) {
        guard
            let info = notification.userInfo,
            let rawType = info[AVAudioSessionInterruptionTypeKey] as? UInt,
            let type = AVAudioSession.InterruptionType(rawValue: rawType),
            type == .ended,
            isRunning
        else { return }
        try? AVAudioSession.sharedInstance().setActive(true)
        try? engine?.start()
    }
}
