import Foundation

enum ServiceState: Equatable {
    case stopped, starting, running, stopping, failed(String)
    var title: String {
        switch self {
        case .stopped: return "Stopped"
        case .starting: return "Starting"
        case .running: return "Running"
        case .stopping: return "Stopping"
        case .failed: return "Unavailable"
        }
    }
    var busy: Bool { self == .starting || self == .stopping }
}

@MainActor
final class ServiceController {
    let home = URL(string: "http://127.0.0.1:18765/")!
    let dataURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/OpenArtifact")
    let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/OpenArtifact/service.log")
    private(set) var state = ServiceState.stopped { didSet { onChange?() } }
    private(set) var owned = false
    private(set) var token: String?
    private var instance = ""
    private var checkout: URL?
    private var process: Process?
    private var timer: Timer?
    private var probing = false
    private var quitting: (() -> Void)?
    var onChange: (() -> Void)?

    func start() {
        guard !state.busy, state != .running else { return }
        state = .starting
        Task {
            do {
                try prepare()
                if let existing = await health() {
                    owned = existing["desktop_id"] as? String == instance
                    if !owned { token = nil }
                    state = .running
                    monitor()
                    finishQuitIfNeeded()
                    return
                }
                owned = true
                try compose(["up", "--build", "-d", "--wait", "--wait-timeout", "120"]) { [weak self] status in
                    guard let self = self else { return }
                    Task {
                        if status == 0, let info = await self.health(), info["desktop_id"] as? String == self.instance {
                            self.state = .running
                            self.monitor()
                        } else {
                            self.state = .failed("Could not start the desktop service. Start Docker Desktop, then choose Start / Retry. See View Logs for details.")
                        }
                        self.finishQuitIfNeeded()
                    }
                }
            } catch {
                state = .failed(error.localizedDescription)
                finishQuitIfNeeded()
            }
        }
    }

    func stop(completion: (() -> Void)? = nil) {
        guard owned else { completion?(); return }
        guard !state.busy else { return }
        timer?.invalidate()
        state = .stopping
        do {
            try compose(["stop", "--timeout", "30"]) { [weak self] status in
                guard let self = self else { return }
                self.state = status == 0 ? .stopped : .failed("Could not stop the desktop service. Check Docker Desktop and View Logs.")
                completion?()
                self.finishQuitIfNeeded()
            }
        } catch {
            state = .failed(error.localizedDescription)
            completion?()
            finishQuitIfNeeded()
        }
    }

    func shutdown(_ completion: @escaping () -> Void) {
        quitting = completion
        if !state.busy { finishQuitIfNeeded() }
    }

    private func finishQuitIfNeeded() {
        guard let done = quitting else { return }
        quitting = nil
        if owned && state != .stopped { stop(completion: done) } else { done() }
    }

    private func prepare() throws {
        guard let resources = Bundle.main.resourceURL else { throw DesktopError.message("App resources are missing.") }
        let root = try String(contentsOf: resources.appendingPathComponent("checkout.txt"), encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard FileManager.default.fileExists(atPath: root + "/desktop/compose.yml") else {
            throw DesktopError.message("The checkout has moved. Rebuild with make desktop.")
        }
        checkout = URL(fileURLWithPath: root)
        try FileManager.default.createDirectory(at: dataURL, withIntermediateDirectories: true,
                                              attributes: [.posixPermissions: 0o700])
        let identity = dataURL.appendingPathComponent("instance.txt")
        if FileManager.default.fileExists(atPath: identity.path) {
            instance = try String(contentsOf: identity, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            guard UUID(uuidString: instance) != nil else { throw DesktopError.message("The desktop instance identity is invalid.") }
        } else {
            instance = UUID().uuidString
            try instance.write(to: identity, atomically: true, encoding: .utf8)
        }
        token = try Credential.load()
    }

    private func compose(_ arguments: [String], completion: @escaping (Int32) -> Void) throws {
        guard let checkout = checkout, let token = token else { throw DesktopError.message("The desktop service is not configured.") }
        let candidates = ["/usr/local/bin/docker", "/opt/homebrew/bin/docker", "/Applications/Docker.app/Contents/Resources/bin/docker"]
        guard let docker = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            throw DesktopError.message("Install and start Docker Desktop, then choose Start / Retry.")
        }
        try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let output = try FileHandle(forWritingTo: logURL)
        try output.seekToEnd()
        try output.write(contentsOf: Data("\n[\(Date())] docker compose \(arguments.joined(separator: " "))\n".utf8))
        let child = Process()
        child.executableURL = URL(fileURLWithPath: docker)
        child.currentDirectoryURL = checkout
        child.arguments = ["compose", "--project-name", "openartifact-desktop", "--file", "desktop/compose.yml"] + arguments
        // Finder does not inherit shell setup. Ignore development auth and Compose overrides.
        var environment = ["PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                           "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
                           "OPENARTIFACT_DESKTOP_TOKEN": token, "OPENARTIFACT_DESKTOP_ID": instance,
                           "OPENARTIFACT_DESKTOP_DATA": dataURL.path]
        for key in ["DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"] {
            environment[key] = ProcessInfo.processInfo.environment[key]
        }
        child.environment = environment
        child.standardOutput = output
        child.standardError = output
        child.terminationHandler = { child in
            try? output.close()
            DispatchQueue.main.async { [weak self] in
                self?.process = nil
                completion(child.terminationStatus)
            }
        }
        process = child
        do { try child.run() } catch { process = nil; try? output.close(); throw error }
    }

    private func health() async -> [String: Any]? {
        var request = URLRequest(url: home.appendingPathComponent("health/"))
        request.timeoutInterval = 3
        request.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let info = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              info["status"] as? String == "ok" else { return nil }
        return info
    }

    private func monitor() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self = self, !self.state.busy, !self.probing else { return }
                self.probing = true
                let info = await self.health()
                self.probing = false
                guard !self.state.busy, self.state != .stopped else { return }
                if let info = info {
                    if self.owned && info["desktop_id"] as? String != self.instance {
                        self.owned = false
                        self.token = nil
                        self.state = .failed("The service at the desktop address changed. It will not be stopped by this app.")
                        self.timer?.invalidate()
                    } else if self.state != .running { self.state = .running }
                } else if self.state == .running {
                    self.state = .failed("The service is not responding. Check Docker Desktop, then choose Start / Retry.")
                }
            }
        }
    }
}
