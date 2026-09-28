// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SandboxFixture",
    products: [.library(name: "SandboxFixture", targets: ["SandboxFixture"])],
    targets: [
        .target(name: "SandboxFixture"),
        .testTarget(name: "SandboxFixtureTests", dependencies: ["SandboxFixture"])
    ]
)
