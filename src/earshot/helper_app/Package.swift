// swift-tools-version:5.9
import Foundation
import PackageDescription

// The signed helper (D-016): it owns the AirPods mic, device changes and head motion for earshotd.
// Its Info.plist is embedded in the executable, and build.sh also wraps it in an app bundle, so
// macOS asks for the mic and motion in its own name ("Earshot").
let infoPlist = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent()
    .appendingPathComponent("Sources/EarshotMotion/Info.plist")
    .path

let package = Package(
    name: "EarshotMotion",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "earshot-motion", targets: ["EarshotMotion"]),
    ],
    targets: [
        .executableTarget(
            name: "EarshotMotion",
            path: "Sources/EarshotMotion",
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
