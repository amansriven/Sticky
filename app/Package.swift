// swift-tools-version:5.10
// Sticky menu bar app. The diagnosis engine is the `sticky` command (Python);
// this app runs `sticky report --compact` and shows the result.
import PackageDescription

let package = Package(
    name: "StickyBar",
    platforms: [.macOS(.v14)],
    targets: [
        // Models, the CLI bridge and notification planning: no UI, fully testable.
        .target(name: "StickyCore", path: "Sources/StickyCore"),
        // The SwiftUI menu bar app.
        .executableTarget(name: "StickyBar", dependencies: ["StickyCore"], path: "Sources/StickyBar"),
        .testTarget(name: "StickyCoreTests", dependencies: ["StickyCore"], path: "Tests/StickyCoreTests",
                    resources: [.copy("Fixtures")]),
    ]
)
