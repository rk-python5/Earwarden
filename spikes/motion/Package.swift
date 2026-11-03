// swift-tools-version:5.9
import Foundation
import PackageDescription

// Embed an Info.plist in the executable so macOS can show a usage reason when the spike asks
// for headphone motion. The linker needs an absolute path, so build it from this manifest's path.
let infoPlist = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent()
    .appendingPathComponent("Sources/MotionSpike/Info.plist")
    .path

let package = Package(
    name: "MotionSpike",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "motion-spike", targets: ["MotionSpike"]),
    ],
    targets: [
        .executableTarget(
            name: "MotionSpike",
            path: "Sources/MotionSpike",
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
