import Cocoa
import WebKit
import Darwin

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var statusItem: NSStatusItem!
    private var backend: Process?
    private var backendURL: URL!
    private var appRoot: URL!
    private var supportRoot: URL!
    private var logHandle: FileHandle?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        configurePaths()
        configureStatusItem()
        configureWindow()
        startBackend()
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopBackend()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }

    private func configurePaths() {
        let resources = Bundle.main.resourceURL!
        appRoot = resources.appendingPathComponent("pdf-epub", isDirectory: true)
        supportRoot = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("PDF to EPUB", isDirectory: true)
        try? FileManager.default.createDirectory(at: supportRoot, withIntermediateDirectories: true)
        try? FileManager.default.createDirectory(
            at: supportRoot.appendingPathComponent("logs", isDirectory: true),
            withIntermediateDirectories: true
        )
        let configURL = supportRoot.appendingPathComponent(".env")
        if !FileManager.default.fileExists(atPath: configURL.path) {
            FileManager.default.createFile(atPath: configURL.path, contents: nil)
        }
    }

    private func configureWindow() {
        webView = WKWebView(frame: .zero)
        webView.navigationDelegate = self

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1180, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "PDF to EPUB"
        window.center()
        window.contentView = webView
        window.delegate = self
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func configureStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "PDF EPUB"

        let menu = NSMenu()
        menu.addItem(menuItem("Show PDF to EPUB", action: #selector(showWindow)))
        menu.addItem(menuItem("Open in Browser", action: #selector(openInBrowser)))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(menuItem("Quit", action: #selector(quitApp), keyEquivalent: "q"))
        statusItem.menu = menu
    }

    private func menuItem(_ title: String, action: Selector, keyEquivalent: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: keyEquivalent)
        item.target = self
        return item
    }

    private func startBackend() {
        let port = findAvailablePort()
        backendURL = URL(string: "http://127.0.0.1:\(port)/login")!

        let process = Process()
        process.currentDirectoryURL = appRoot
        process.executableURL = appRoot.appendingPathComponent(".venv/bin/python")
        process.arguments = [
            appRoot.appendingPathComponent("scripts/run-app.py").path,
            "--no-open",
            "--port",
            "\(port)"
        ]

        var env = ProcessInfo.processInfo.environment
        let binPath = appRoot.appendingPathComponent("bin").path
        let nodePath = appRoot.appendingPathComponent("vendor/node/bin").path
        env["PATH"] = "\(binPath):\(nodePath):/usr/bin:/bin:/usr/sbin:/sbin"
        env["LOCAL_CONFIG_FILE"] = supportRoot.appendingPathComponent(".env").path
        env["LOCAL_DATA_DIR"] = supportRoot.appendingPathComponent("data", isDirectory: true).path
        env["LOCAL_HOST"] = "127.0.0.1"
        env["LOCAL_PORT"] = "\(port)"
        env["LOCAL_PADDLE_MODE"] = "local"
        env["LOCAL_PADDLE_PYTHON"] = appRoot.appendingPathComponent(".venv_paddleocr/bin/python").path
        env["LOCAL_KCC_SOURCE_DIR"] = appRoot.appendingPathComponent("tmp/kcc-source-work").path
        env["PADDLE_PDX_CACHE_HOME"] = supportRoot.appendingPathComponent("models/paddlex", isDirectory: true).path
        env["HF_HOME"] = supportRoot.appendingPathComponent("models/huggingface", isDirectory: true).path
        env["HUGGINGFACE_HUB_CACHE"] = supportRoot.appendingPathComponent("models/huggingface/hub", isDirectory: true).path
        env["XDG_CACHE_HOME"] = supportRoot.appendingPathComponent("models/xdg-cache", isDirectory: true).path
        process.environment = env

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        let logURL = supportRoot.appendingPathComponent("logs/backend.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        logHandle = try? FileHandle(forWritingTo: logURL)
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if !data.isEmpty {
                self?.logHandle?.write(data)
            }
        }

        do {
            try process.run()
            backend = process
            waitForBackend(attempt: 0)
        } catch {
            showStartupError("Could not start the local backend: \(error.localizedDescription)")
        }
    }

    private func stopBackend() {
        backend?.terminate()
        if backend?.isRunning == true {
            DispatchQueue.global().asyncAfter(deadline: .now() + 3) { [weak self] in
                if self?.backend?.isRunning == true {
                    self?.backend?.interrupt()
                }
            }
        }
        backend = nil
        logHandle?.closeFile()
        logHandle = nil
    }

    private func waitForBackend(attempt: Int) {
        if attempt > 120 {
            showStartupError("The local backend did not respond. Check Application Support/PDF to EPUB/logs/backend.log.")
            return
        }

        URLSession.shared.dataTask(with: backendURL) { [weak self] _, response, _ in
            if let http = response as? HTTPURLResponse, http.statusCode < 500 {
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.webView.load(URLRequest(url: self.backendURL))
                }
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                    self?.waitForBackend(attempt: attempt + 1)
                }
            }
        }.resume()
    }

    private func showStartupError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "PDF to EPUB could not start"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.runModal()
    }

    @objc private func showWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func openInBrowser() {
        NSWorkspace.shared.open(backendURL)
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        if let url = navigationAction.request.url, url.path.contains("/download") {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
}

private func findAvailablePort() -> Int {
    let socketFD = socket(AF_INET, SOCK_STREAM, 0)
    if socketFD < 0 {
        return 8000
    }
    defer { close(socketFD) }

    var addr = sockaddr_in()
    addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.stride)
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = in_port_t(0).bigEndian
    addr.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

    let bindResult = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            bind(socketFD, $0, socklen_t(MemoryLayout<sockaddr_in>.stride))
        }
    }
    if bindResult != 0 {
        return 8000
    }

    var actual = sockaddr_in()
    var length = socklen_t(MemoryLayout<sockaddr_in>.stride)
    let nameResult = withUnsafeMutablePointer(to: &actual) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            getsockname(socketFD, $0, &length)
        }
    }
    if nameResult != 0 {
        return 8000
    }
    return Int(UInt16(bigEndian: actual.sin_port))
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
