// Platform-only fixture: no business data, account access, network or persistent storage.
import AppKit
import Darwin

if CommandLine.arguments.count == 5 && CommandLine.arguments[1] == "--isolation-probe" {
    let protected = CommandLine.arguments[2]
    let scratchFile = CommandLine.arguments[3]
    print("READ_DENIED=\((try? Data(contentsOf: URL(fileURLWithPath: protected))) == nil)")
    do {
        try Data("changed".utf8).write(to: URL(fileURLWithPath: protected))
        print("WRITE_DENIED=false")
    } catch { print("WRITE_DENIED=true") }
    do {
        try Data("scratch".utf8).write(to: URL(fileURLWithPath: scratchFile))
        print("SCRATCH_WRITE=true")
    } catch { print("SCRATCH_WRITE=false") }
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    var address = sockaddr_in()
    address.sin_family = sa_family_t(AF_INET)
    address.sin_port = UInt16(CommandLine.arguments[4])!.bigEndian
    address.sin_addr.s_addr = inet_addr("127.0.0.1")
    let connected = withUnsafePointer(to: &address) { pointer in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    print("NETWORK_DENIED=\(connected != 0)")
    close(fd)
    let child = Process()
    child.executableURL = URL(fileURLWithPath: "/usr/bin/true")
    do { try child.run(); child.waitUntilExit(); print("OTHER_EXEC_DENIED=false") }
    catch { print("OTHER_EXEC_DENIED=true") }
    exit(0)
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let window = NSWindow(
    contentRect: NSRect(x: 200, y: 200, width: 400, height: 240),
    styleMask: [.titled, .closable], backing: .buffered, defer: false
)
window.title = "ASE isolated UI probe"
let button = NSButton(checkboxWithTitle: "ASE fixture toggle", target: nil, action: nil)
button.setAccessibilityIdentifier("ase-fixture-toggle")
button.frame = NSRect(x: 40, y: 80, width: 280, height: 40)
window.contentView?.addSubview(button)
window.makeKeyAndOrderFront(nil)
window.orderFrontRegardless()
app.activate(ignoringOtherApps: true)
print("ASE_UI_PID=\(ProcessInfo.processInfo.processIdentifier)")
fflush(stdout)
app.run()
