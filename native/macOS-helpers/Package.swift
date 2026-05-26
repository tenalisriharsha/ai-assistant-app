// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "macOS-helpers",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "calendar-sync", targets: ["CalendarSync"]),
        .executable(name: "spotlight-index", targets: ["SpotlightIndex"]),
    ],
    targets: [
        .target(name: "Shared", dependencies: []),
        .executableTarget(
            name: "CalendarSync",
            dependencies: ["Shared"]
        ),
        .executableTarget(
            name: "SpotlightIndex",
            dependencies: ["Shared"]
        ),
    ]
)
