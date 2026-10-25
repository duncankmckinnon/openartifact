import AppKit
import WebKit

// The prototype uses the checkout's Compose stack. Closing the window leaves it running,
// just like `make up`, so browser sessions and exports can finish.
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var status: NSTextField!
    var startup: Process?
    var logURL: URL!
    let home = URL(string: "http://127.0.0.1:8765/")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit OpenArtifact", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        NSApp.mainMenu = menu

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 840),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "OpenArtifact"
        window.center()
        webView = WKWebView(frame: window.contentView!.bounds)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.uiDelegate = self
        window.contentView!.addSubview(webView)
        status = NSTextField(wrappingLabelWithString: "Starting OpenArtifact...\nThe first launch builds the Docker images and may take several minutes.")
        status.frame = NSRect(x: 40, y: 340, width: 800, height: 120)
        status.autoresizingMask = [.maxXMargin, .minYMargin]
        window.contentView!.addSubview(status)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startServices()
    }

    func startServices() {
        do {
            let resources = Bundle.main.resourceURL!
            let checkout = try String(contentsOf: resources.appendingPathComponent("checkout.txt"), encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard FileManager.default.fileExists(atPath: checkout + "/docker-compose.yml") else {
                throw NSError(domain: "OpenArtifact", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "The source checkout has moved. Rebuild the app with make desktop."])
            }
            let candidates = ["/usr/local/bin/docker", "/opt/homebrew/bin/docker", "/Applications/Docker.app/Contents/Resources/bin/docker"]
            guard let docker = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
                throw NSError(domain: "OpenArtifact", code: 2, userInfo: [NSLocalizedDescriptionKey:
                    "Install and start Docker Desktop, then reopen OpenArtifact."])
            }
            let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/OpenArtifact")
            try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
            logURL = logs.appendingPathComponent("startup.log")
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
            let output = try FileHandle(forWritingTo: logURL)
            let process = Process()
            process.executableURL = URL(fileURLWithPath: docker)
            process.arguments = ["compose", "up", "--build", "-d", "--wait"]
            process.currentDirectoryURL = URL(fileURLWithPath: checkout)
            var environment = ProcessInfo.processInfo.environment
            environment["PATH"] = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            environment["OPENARTIFACT_PORT"] = "8765"
            process.environment = environment
            process.standardOutput = output
            process.standardError = output
            process.terminationHandler = { [weak self] child in
                try? output.close()
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.startup = nil
                    if child.terminationStatus == 0 {
                        self.checkHealth()
                    } else {
                        self.fail("Services could not start. Make sure Docker Desktop is running.\nSee \(self.logURL.path) for details.")
                    }
                }
            }
            startup = process
            try process.run()
        } catch {
            fail(error.localizedDescription)
        }
    }

    func checkHealth() {
        URLSession.shared.dataTask(with: home.appendingPathComponent("health/")) { [weak self] _, response, error in
            DispatchQueue.main.async {
                guard let self = self else { return }
                guard error == nil, (response as? HTTPURLResponse)?.statusCode == 200 else {
                    self.fail("Services started, but OpenArtifact did not answer its health check. Reopen the app to retry.")
                    return
                }
                self.webView.load(URLRequest(url: self.home))
            }
        }.resume()
    }

    func fail(_ message: String) {
        status.stringValue = message
        status.isHidden = false
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        status.isHidden = true
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        fail(error.localizedDescription)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == home.scheme && url.host == home.host && url.port == home.port {
            if navigationAction.targetFrame == nil { webView.load(navigationAction.request) }
            decisionHandler(navigationAction.targetFrame == nil ? .cancel : .allow)
        } else {
            if ["https", "http", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
