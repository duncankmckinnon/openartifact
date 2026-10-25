import AppKit
import WebKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler, NSUserInterfaceValidations {
    let service = ServiceController()
    var window: NSWindow!
    var webView: WKWebView!
    var status: NSTextField!
    var statusItem: NSStatusItem!
    var connectionWindow: NSWindow?
    var connectionStatus: NSTextField?
    var lastState = ServiceState.stopped
    var authenticated = false
    var authenticating = false
    var quitReady = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        service.onChange = { [weak self] in self?.serviceChanged() }
        showWindow()
        service.start()
    }

    func buildMenu() {
        let menu = NSMenu()
        let item = NSMenuItem()
        menu.addItem(item)
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: "Open OpenArtifact", action: #selector(showWindow), keyEquivalent: "0").target = self
        applicationMenu.addItem(withTitle: "Connect an Agent...", action: #selector(connectAgent), keyEquivalent: "k").target = self
        applicationMenu.addItem(withTitle: "Start / Retry", action: #selector(startService), keyEquivalent: "r").target = self
        applicationMenu.addItem(withTitle: "Stop Service", action: #selector(stopService), keyEquivalent: "").target = self
        applicationMenu.addItem(withTitle: "View Logs", action: #selector(viewLogs), keyEquivalent: "").target = self
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: "Quit OpenArtifact", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = applicationMenu
        let fileItem = NSMenuItem()
        menu.addItem(fileItem)
        let file = NSMenu(title: "File")
        file.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileItem.submenu = file
        let editItem = NSMenuItem()
        menu.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        for (title, action, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                                     ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = edit
        NSApp.mainMenu = menu
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "doc.richtext", accessibilityDescription: "OpenArtifact service")
        updateStatusMenu()
    }

    func updateStatusMenu() {
        let menu = NSMenu()
        menu.autoenablesItems = false
        let ownership = service.state == .running ? (service.owned ? " - managed by app" : " - existing service") : ""
        menu.addItem(withTitle: "OpenArtifact: \(service.state.title)\(ownership)", action: nil, keyEquivalent: "").isEnabled = false
        menu.addItem(.separator())
        func add(_ title: String, _ action: Selector, enabled: Bool = true) {
            let item = menu.addItem(withTitle: title, action: action, keyEquivalent: "")
            item.target = self
            item.isEnabled = enabled
        }
        add("Open OpenArtifact", #selector(showWindow))
        add("Connect an Agent...", #selector(connectAgent), enabled: service.state == .running)
        add("Copy MCP URL", #selector(copyURL))
        menu.addItem(.separator())
        add("Start / Retry", #selector(startService), enabled: !service.state.busy && service.state != .running)
        add("Stop Service", #selector(stopService), enabled: service.owned && !service.state.busy && service.state != .stopped)
        add("View Logs", #selector(viewLogs))
        menu.addItem(.separator())
        add("Quit OpenArtifact", #selector(quit))
        statusItem.menu = menu
        statusItem.button?.toolTip = "OpenArtifact: \(service.state.title)"
    }

    func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 840),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "OpenArtifact"
        window.isReleasedWhenClosed = false
        window.center()
        let content = WKUserContentController()
        // Clipboard only: no credential or service-management bridge is exposed to authored artifacts.
        content.add(self, name: "copyText")
        content.addUserScript(WKUserScript(source: """
            if (location.pathname === '/' || /^\\/edit\\/[0-9a-f-]+$/.test(location.pathname)) {
                Object.defineProperty(navigator.clipboard, 'writeText', {value: (text) => {
                    window.webkit.messageHandlers.copyText.postMessage(String(text));
                    return Promise.resolve();
                }});
            }
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = content
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        window.contentView!.addSubview(webView)
        status = NSTextField(wrappingLabelWithString: "Starting OpenArtifact...")
        status.frame = NSRect(x: 40, y: 340, width: 900, height: 140)
        status.autoresizingMask = [.maxXMargin, .minYMargin]
        window.contentView!.addSubview(status)
    }

    func serviceChanged() {
        updateStatusMenu()
        if service.state == .running {
            if lastState != .running { loadViewer() }
        } else {
            authenticated = false
            webView.isHidden = true
            status.isHidden = false
            switch service.state {
            case .starting: status.stringValue = "Starting OpenArtifact...\nThe first launch builds Docker images and can take several minutes. You can close this window; the menu bar shows progress."
            case .stopping: status.stringValue = "Stopping the desktop service..."
            case .stopped: status.stringValue = "Service stopped.\nChoose Start / Retry from the OpenArtifact menu bar icon."
            case .failed(let message): status.stringValue = message
            case .running: break
            }
        }
        lastState = service.state
    }

    func loadViewer() {
        guard service.state == .running, !authenticating else { return }
        guard service.owned, let token = service.token else {
            webView.isHidden = false
            webView.load(URLRequest(url: service.home))
            return
        }
        authenticating = true
        Task {
            do {
                var request = URLRequest(url: service.home.appendingPathComponent("login/desktop"))
                request.httpMethod = "POST"
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                let session = URLSession(configuration: .ephemeral)
                defer { session.invalidateAndCancel() }
                let (_, response) = try await session.data(for: request)
                guard let response = response as? HTTPURLResponse, response.statusCode == 204 else {
                    throw DesktopError.message("The desktop credential was refused. Check the service logs.")
                }
                let fields = response.allHeaderFields.reduce(into: [String: String]()) {
                    if let key = $1.key as? String, let value = $1.value as? String { $0[key] = value }
                }
                let cookies = HTTPCookie.cookies(withResponseHeaderFields: fields, for: service.home)
                guard cookies.contains(where: { $0.name == "oa_session" }) else { throw DesktopError.message("No viewer session was returned.") }
                for cookie in cookies {
                    await withCheckedContinuation { continuation in
                        webView.configuration.websiteDataStore.httpCookieStore.setCookie(cookie) { continuation.resume() }
                    }
                }
                guard service.state == .running else { authenticating = false; return }
                authenticated = true
                webView.isHidden = false
                webView.load(URLRequest(url: service.home))
            } catch {
                status.stringValue = error.localizedDescription
                status.isHidden = false
            }
            authenticating = false
        }
    }

    @objc func showWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if service.state == .running && !authenticated { loadViewer() }
    }
    @objc func startService() { service.start() }
    @objc func stopService() { connectionWindow?.close(); service.stop() }
    @objc func quit() { NSApp.terminate(nil) }
    func validateUserInterfaceItem(_ item: NSValidatedUserInterfaceItem) -> Bool {
        switch item.action {
        case #selector(startService): return !service.state.busy && service.state != .running
        case #selector(stopService): return service.owned && !service.state.busy && service.state != .stopped
        case #selector(connectAgent): return service.state == .running
        default: return true
        }
    }
    @objc func viewLogs() {
        if FileManager.default.fileExists(atPath: service.logURL.path) { NSWorkspace.shared.open(service.logURL) }
        else { status.stringValue = "No service log has been written yet."; status.isHidden = false; showWindow() }
    }
    func copy(_ value: String) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(value, forType: .string) }
    @objc func copyURL() { copy(service.home.appendingPathComponent("mcp/").absoluteString) }

    @objc func connectAgent() {
        guard service.state == .running else { showWindow(); return }
        if let existing = connectionWindow { existing.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return }
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 620, height: 310),
                             styleMask: [.titled, .closable], backing: .buffered, defer: false)
        panel.title = "Connect an Agent"
        panel.isReleasedWhenClosed = false
        let label = NSTextField(wrappingLabelWithString: "Connect Claude Code or local Codex to OpenArtifact.\n\n\(service.home.appendingPathComponent("mcp/").absoluteString)\n\nSetup snippets include your private access credential. Paste them only into your agent's configuration. Remote web connectors need a hosted service.")
        label.frame = NSRect(x: 24, y: 130, width: 572, height: 155)
        panel.contentView!.addSubview(label)
        for (index, item) in [("Copy Claude Code Setup", #selector(copyClaude)), ("Copy Codex Config", #selector(copyCodex)), ("Test Connection", #selector(testConnection))].enumerated() {
            let button = NSButton(title: item.0, target: self, action: item.1)
            button.frame = NSRect(x: 20 + index * 195, y: 88, width: 190, height: 32)
            button.bezelStyle = .rounded
            button.isEnabled = service.owned && service.token != nil
            panel.contentView!.addSubview(button)
        }
        let detail = NSTextField(wrappingLabelWithString: service.owned ? "Claude Code: paste the command into Terminal. Codex: add the config to ~/.codex/config.toml, then restart the client." : "This is an existing service. Open its MCP dialog to configure authentication; this app does not hold its credential.")
        detail.frame = NSRect(x: 24, y: 16, width: 572, height: 64)
        panel.contentView!.addSubview(detail)
        connectionStatus = detail
        connectionWindow = panel
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc func copyClaude() {
        guard service.state == .running, service.owned, let token = service.token else { return }
        copy("claude mcp add --scope user --transport http openartifact \(service.home.appendingPathComponent("mcp/").absoluteString) --header 'Authorization: Bearer \(token)'")
        connectionStatus?.stringValue = "Copied. Run in Terminal, then use /mcp in Claude Code to check the connection. This command includes a private credential."
    }
    @objc func copyCodex() {
        guard service.state == .running, service.owned, let token = service.token else { return }
        copy("[mcp_servers.openartifact]\nurl = \"\(service.home.appendingPathComponent("mcp/").absoluteString)\"\nhttp_headers = { Authorization = \"Bearer \(token)\" }\n")
        connectionStatus?.stringValue = "Copied. Add to ~/.codex/config.toml, then restart the client. This configuration includes a private credential."
    }
    @objc func testConnection() {
        guard service.state == .running, service.owned, let token = service.token else { return }
        connectionStatus?.stringValue = "Checking authenticated MCP initialization and tool discovery..."
        Task {
            do {
                let count = try await MCPClient.check(url: service.home.appendingPathComponent("mcp/"), token: token)
                connectionStatus?.stringValue = "Connected and authenticated. Discovered \(count) MCP tools. No artifacts were changed."
            } catch { connectionStatus?.stringValue = error.localizedDescription }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "copyText", message.frameInfo.isMainFrame,
              let url = message.frameInfo.request.url, sameOrigin(url),
              url.path == "/" || url.path.hasPrefix("/edit/"), let text = message.body as? String else { return }
        copy(text)
    }
    func sameOrigin(_ url: URL) -> Bool { url.scheme == service.home.scheme && url.host == service.home.host && url.port == service.home.port }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { status.isHidden = true }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        status.stringValue = error.localizedDescription
        status.isHidden = false
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if sameOrigin(url) {
            if navigationAction.targetFrame == nil { webView.load(navigationAction.request) }
            decisionHandler(navigationAction.targetFrame == nil ? .cancel : .allow)
        } else {
            if navigationAction.navigationType == .linkActivated && ["https", "http", "mailto"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { showWindow(); return true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitReady { return .terminateNow }
        DispatchQueue.main.async {
            self.service.shutdown { [weak self] in
                guard let self = self else { return }
                if self.service.owned, case .failed(let message) = self.service.state {
                    sender.reply(toApplicationShouldTerminate: false)
                    self.showWindow()
                    let alert = NSAlert()
                    alert.messageText = "The desktop service could not stop"
                    alert.informativeText = message
                    alert.runModal()
                } else {
                    self.quitReady = true
                    sender.reply(toApplicationShouldTerminate: true)
                }
            }
        }
        return .terminateLater
    }
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.regular)
    app.run()
}
