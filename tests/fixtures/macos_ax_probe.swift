// Read-only platform capability probe, never used as business acceptance evidence.
import ApplicationServices
import Foundation

guard CommandLine.arguments.count == 2, let pid = Int32(CommandLine.arguments[1]) else {
    exit(2)
}
guard AXIsProcessTrusted() else {
    print("AX_NOT_TRUSTED")
    exit(3)
}
let root = AXUIElementCreateApplication(pid)
AXUIElementSetMessagingTimeout(root, 2)
var count = 0
func attribute(_ node: AXUIElement, _ key: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(node, key as CFString, &value) == .success ? value : nil
}
func walk(_ node: AXUIElement, _ depth: Int) {
    guard depth < 24, count < 400 else { return }
    count += 1
    var fields: [String: String] = [:]
    for key in ["AXRole", "AXTitle", "AXDescription", "AXIdentifier", "AXValue"] {
        if let value = attribute(node, key) { fields[key] = String(describing: value).prefix(400).description }
    }
    if let bytes = try? JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys]),
       let line = String(data: bytes, encoding: .utf8) { print(line) }
    if let children = attribute(node, "AXChildren") as? [AXUIElement] {
        for child in children { walk(child, depth + 1) }
    }
}
// Never traverse the application menu bar: its Apple menu contains host recent items.
if let windows = attribute(root, "AXWindows") as? [AXUIElement] {
    for window in windows { walk(window, 0) }
}
