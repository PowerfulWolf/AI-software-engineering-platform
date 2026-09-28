// Trusted ASE driver. Only one child PID's exact titled windows, never menus/global UI.
import ApplicationServices
import AppKit
import CryptoKit
import Foundation
import ImageIO
import ScreenCaptureKit

struct Step: Decodable {
    let action: String
    let role: String?
    let attribute: String?
    let value: String?
    let index: Int
    let capture_window: Bool?
    let scroll_position: Double?
}
struct Input: Decodable {
    let pid: Int32
    let window_title: String
    let step: Step
}
struct Node: Encodable {
    let path: String
    let attributes: [String: String]
}
struct Output: Encodable {
    let pid: Int32
    let action: String
    let nodes: [Node]
    var error: String?
    var diagnostic: String? = nil
    var diagnostics: Diagnostics? = nil
    var capture: Capture? = nil
}
struct Png: Encodable {
    let media_type = "image/png"
    let data_base64: String
    let sha256: String
    let width: Int
    let height: Int
}
struct Capture: Encodable {
    let window_id: UInt32
    let image: Png
}
enum CaptureError: Error { case unavailable }

@available(macOS 14.0, *)
@MainActor
func captureWindow(_ input: Input) async throws -> Capture {
    guard input.step.action == "snapshot", CGPreflightScreenCaptureAccess(),
          sessionStatus() == "READY" else { throw CaptureError.unavailable }
    // A command-line helper must initialize its AppKit WindowServer connection before
    // constructing a ScreenCaptureKit window filter. This does not activate/create UI.
    _ = NSApplication.shared
    // Inspect transient inventory solely to select this exact child window. Never capture
    // a display/rectangle or return another application's metadata or pixels.
    let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
    let windows = content.windows.filter {
        $0.owningApplication?.processID == input.pid && $0.title == input.window_title
            && $0.windowLayer == 0
    }
    guard windows.count == 1, let window = windows.first,
          window.frame.width > 0, window.frame.height > 0 else { throw CaptureError.unavailable }
    let scale = min(1.0, 1800.0 / window.frame.width, 1800.0 / window.frame.height)
    let configuration = SCStreamConfiguration()
    configuration.width = max(1, Int(window.frame.width * scale))
    configuration.height = max(1, Int(window.frame.height * scale))
    configuration.showsCursor = false
    configuration.ignoreShadowsSingleWindow = true
    configuration.shouldBeOpaque = true
    configuration.scalesToFit = true
    let pixels = try await SCScreenshotManager.captureImage(
        contentFilter: SCContentFilter(desktopIndependentWindow: window), configuration: configuration)
    guard sessionStatus() == "READY", pixels.width <= 1800, pixels.height <= 1800 else {
        throw CaptureError.unavailable
    }
    let data = NSMutableData()
    guard let destination = CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil) else {
        throw CaptureError.unavailable
    }
    CGImageDestinationAddImage(destination, pixels, nil)
    guard CGImageDestinationFinalize(destination), data.length <= 400_000 else {
        throw CaptureError.unavailable
    }
    let bytes = data as Data
    return Capture(window_id: window.windowID, image: Png(data_base64: bytes.base64EncodedString(),
        sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(),
        width: pixels.width, height: pixels.height))
}
struct Diagnostics: Encodable {
    let session_status: String
    let ax_trusted: Bool
    let native_window_count: Int?
    let ax_status: Int32
    let ax_window_count: Int?
}
struct Session: Encodable {
    let status: String
}
func sessionStatus() -> String {
    guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else {
        return "SESSION_UNAVAILABLE"
    }
    if session["CGSSessionScreenIsLocked"] as? Bool == true { return "SESSION_LOCKED" }
    guard session["kCGSSessionOnConsoleKey"] as? Bool == true,
          session["kCGSessionLoginDoneKey"] as? Bool == true else {
        return "SESSION_UNAVAILABLE"
    }
    return "READY"
}
func attr(_ node: AXUIElement, _ key: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(node, key as CFString, &value) == .success ? value : nil
}
func diagnose(_ input: Input) -> Diagnostics {
    let target = AXUIElementCreateApplication(input.pid)
    AXUIElementSetMessagingTimeout(target, 1)
    var raw: CFTypeRef?
    let code = AXUIElementCopyAttributeValue(target, "AXWindows" as CFString, &raw)
    // WindowServer exposes no per-PID query. Only retain the exact child's count;
    // never return other processes' window metadata, titles, images or AX roots.
    let windows = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]]
    let count = windows?.filter {
        ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == input.pid
    }.count
    return Diagnostics(session_status: sessionStatus(), ax_trusted: AXIsProcessTrusted(),
        native_window_count: count, ax_status: code.rawValue,
        ax_window_count: (raw as? [AXUIElement])?.count)
}
func textValue(_ value: CFTypeRef) -> String {
    if CFGetTypeID(value) == AXValueGetTypeID() {
        let ax = unsafeBitCast(value, to: AXValue.self)
        if AXValueGetType(ax) == .cgPoint {
            var point = CGPoint.zero
            if AXValueGetValue(ax, .cgPoint, &point) { return "\(point.x),\(point.y)" }
        }
        if AXValueGetType(ax) == .cgSize {
            var size = CGSize.zero
            if AXValueGetValue(ax, .cgSize, &size) { return "\(size.width),\(size.height)" }
        }
    }
    return String(describing: value).prefix(500).description
}
func run(_ input: Input) throws -> Output {
    let session = sessionStatus()
    guard session == "READY" else {
        return Output(pid: input.pid, action: input.step.action, nodes: [], error: session)
    }
    guard input.pid > 1, AXIsProcessTrusted() else {
        return Output(pid: input.pid, action: input.step.action, nodes: [], error: "AX_UNAVAILABLE")
    }
    let app = AXUIElementCreateApplication(input.pid)
    AXUIElementSetMessagingTimeout(app, 1)
    func windows() -> [AXUIElement] {
        (attr(app, "AXWindows") as? [AXUIElement] ?? []).filter {
            (attr($0, "AXRole") as? String) == "AXWindow" && (attr($0, "AXTitle") as? String) == input.window_title
        }
    }
    var nodes: [Node] = []
    var targets: [AXUIElement] = []
    var scrollbars: [AXUIElement] = []
    func walk(_ node: AXUIElement, _ path: String, _ depth: Int) {
        guard depth < 28, nodes.count < 1000 else { return }
        var fields: [String: String] = [:]
        for key in ["AXRole", "AXTitle", "AXDescription", "AXIdentifier", "AXValue", "AXEnabled", "AXHelp", "AXPosition", "AXSize", "AXOrientation"] {
            if let value = attr(node, key) { fields[key] = textValue(value) }
        }
        // A target app may contain embedded menus; they are outside this capability.
        guard fields["AXRole"] != "AXMenuBar", fields["AXRole"] != "AXMenu" else { return }
        nodes.append(Node(path: path, attributes: fields))
        if fields["AXRole"] == "AXScrollBar", fields["AXOrientation"] == "AXVerticalOrientation" {
            scrollbars.append(node)
        }
        if fields["AXRole"] == input.step.role,
           let key = input.step.attribute, fields[key] == input.step.value { targets.append(node) }
        if let children = attr(node, "AXChildren") as? [AXUIElement] {
            for (index, child) in children.enumerated() { walk(child, "\(path).\(index)", depth + 1) }
        }
    }
    for (index, window) in windows().enumerated() { walk(window, "\(index)", 0) }
    guard !nodes.isEmpty else {
        var raw: CFTypeRef?
        let code = AXUIElementCopyAttributeValue(app, "AXWindows" as CFString, &raw)
        let count = (raw as? [AXUIElement])?.count ?? -1
        let titles = (raw as? [AXUIElement] ?? []).map { String(describing: attr($0, "AXTitle")) }
        return Output(pid: input.pid, action: input.step.action, nodes: [], error: "WINDOW_UNAVAILABLE",
            diagnostic: "AXWindows status=\(code.rawValue) count=\(count) titles=\(titles) expected=\(input.window_title)")
    }
    if input.step.action == "scroll" {
        let currentSession = sessionStatus()
        guard currentSession == "READY" else {
            return Output(pid: input.pid, action: input.step.action, nodes: [], error: currentSession)
        }
        guard let position = input.step.scroll_position, position.isFinite,
              (0.0...1.0).contains(position), input.step.role == nil,
              input.step.attribute == nil, input.step.value == nil, input.step.index == 0,
              input.step.capture_window != true, scrollbars.count == 1,
              let scrollbar = scrollbars.first, (attr(scrollbar, "AXEnabled") as? Bool) == true else {
            return Output(pid: input.pid, action: input.step.action, nodes: nodes, error: "SCROLL_UNAVAILABLE",
                diagnostic: "vertical scrollbar count=\(scrollbars.count); requires one enabled exact-window scrollbar")
        }
        var settable = DarwinBoolean(false)
        guard AXUIElementIsAttributeSettable(scrollbar, "AXValue" as CFString, &settable) == .success,
              settable.boolValue,
              AXUIElementSetAttributeValue(scrollbar, "AXValue" as CFString, NSNumber(value: position)) == .success else {
            return Output(pid: input.pid, action: input.step.action, nodes: nodes, error: "SCROLL_UNAVAILABLE")
        }
        Thread.sleep(forTimeInterval: 0.3)
        guard let observed = attr(scrollbar, "AXValue") as? NSNumber,
              abs(observed.doubleValue - position) <= 0.02 else {
            return Output(pid: input.pid, action: input.step.action, nodes: nodes, error: "SCROLL_UNCONFIRMED")
        }
        nodes = []; targets = []; scrollbars = []
        for (index, window) in windows().enumerated() { walk(window, "\(index)", 0) }
    } else if input.step.action == "press" {
        let currentSession = sessionStatus()
        guard currentSession == "READY" else {
            return Output(pid: input.pid, action: input.step.action, nodes: [], error: currentSession)
        }
        guard ["AXButton", "AXCheckBox", "AXLink"].contains(input.step.role ?? ""),
              input.step.role != "AXLink" ||
                (input.step.attribute == "AXIdentifier" && input.step.index == 0 && targets.count == 1),
              input.step.index >= 0, input.step.index < targets.count else {
            return Output(pid: input.pid, action: input.step.action, nodes: nodes, error: "TARGET_UNAVAILABLE")
        }
        guard AXUIElementPerformAction(targets[input.step.index], kAXPressAction as CFString) == .success else {
            return Output(pid: input.pid, action: input.step.action, nodes: nodes, error: "ACTION_FAILED")
        }
        Thread.sleep(forTimeInterval: 0.3)
        nodes = []; targets = []
        for (index, window) in windows().enumerated() { walk(window, "\(index)", 0) }
    } else if input.step.action != "snapshot" {
        return Output(pid: input.pid, action: input.step.action, nodes: [], error: "UNKNOWN_ACTION")
    }
    return Output(pid: input.pid, action: input.step.action, nodes: nodes, error: nil)
}
if CommandLine.arguments.dropFirst().elementsEqual(["--session-check"]) {
    do {
        FileHandle.standardOutput.write(try JSONEncoder().encode(Session(status: sessionStatus())))
        exit(0)
    } catch { exit(2) }
}
Task { @MainActor in
  do {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count <= 8000 else { exit(2) }
    let input = try JSONDecoder().decode(Input.self, from: data)
    var result = try run(input)
    if input.step.capture_window == true && result.error == nil {
        do {
            guard #available(macOS 14.0, *) else { throw CaptureError.unavailable }
            result.capture = try await captureWindow(input)
        } catch {
            let status = sessionStatus()
            result.error = status == "READY" ? "SCREEN_CAPTURE_UNAVAILABLE" : status
        }
    }
    result.diagnostics = diagnose(input)
    let encoded = try JSONEncoder().encode(result)
    FileHandle.standardOutput.write(encoded)
    exit(result.error == nil ? 0 : 1)
  } catch {
    print("{\"error\":\"DRIVER_INPUT_INVALID\"}")
    exit(2)
  }
}
RunLoop.main.run()
