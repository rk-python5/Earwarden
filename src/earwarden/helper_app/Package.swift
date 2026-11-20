// swift-tools-version:5.9
import Foundation
import PackageDescription

// The signed helper (D-016): it owns the AirPods mic, device changes and head motion for earwardend.
// Its Info.plist is embedded in the executable, and build.sh also wraps it in an app bundle, so
// macOS asks for the mic and motion in its own name ("Earwarden").
let infoPlist = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent()
    .appendingPathComponent("Sources/EarwardenMotion/Info.plist")
    .path

let package = Package(
    name: "EarwardenMotion",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "earwarden-motion", targets: ["EarwardenMotion"]),
    ],
    targets: [
        .executableTarget(
            name: "EarwardenMotion",
            path: "Sources/EarwardenMotion",
            exclude: ["Info.plist"],
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", infoPlist,
                ]),
            ]
        ),
    ]
)
