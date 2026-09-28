// Platform-only SwiftUI launch fixture: no business source or persistent data.
import SwiftUI

@main
struct ASESwiftUIProbe: App {
    var body: some Scene {
        WindowGroup("ASE isolated UI probe") {
            ProbeContent()
        }
    }
}

struct ProbeContent: View {
    @State private var linkPressCount = 0

    var body: some View {
        VStack {
            Text("ASE SwiftUI launch fixture")
                .accessibilityIdentifier("ase-swiftui-banner")
            Button("Only this fixture") { linkPressCount += 1 }
                .buttonStyle(.link)
                .accessibilityIdentifier("ase-swiftui-link")
            Text("Link presses: \(linkPressCount)")
                .accessibilityIdentifier("ase-swiftui-link-count")
            HStack {
                scrollContent
                if CommandLine.arguments.contains("--mock-two-scrolls") { scrollContent }
            }
            .frame(height: 180)
        }
        .frame(width: 400, height: 300)
    }

    private var scrollContent: some View {
        ScrollView {
            VStack {
                Text("VISIBLE TOP")
                Color.blue.frame(height: 650)
                Text("VISIBLE BOTTOM")
                    .accessibilityIdentifier("ase-scroll-bottom")
            }
            .frame(maxWidth: .infinity)
        }
    }
}
