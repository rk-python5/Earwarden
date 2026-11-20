// Earwarden Step 0 head-motion spike: AirPods head motion through CMHeadphoneMotionManager.
//
//   motion-spike calibrate           nod, then shake, to see which axis carries each gesture
//   motion-spike count [--minutes N] count nods and shakes during normal work (false positives)
//   motion-spike log                 stream rotation rate and attitude as JSON lines
//
// Options: --threshold R (rad/s, default 1.0), --window S (seconds between the two opposite
// swings, default 1.2), --pitch-axis x|y|z (default x), --yaw-axis x|y|z (default z).
// The detector is the plan's v1: two rotation-rate peaks of opposite sign within the window.

import CoreMotion
import Foundation

struct Options {
    var mode = "count"
    var minutes = 60.0
    var threshold = 1.0
    var window = 1.2
    var pitchAxis = "x"
    var yawAxis = "z"
}

func parseOptions() -> Options {
    var options = Options()
    var arguments = CommandLine.arguments.dropFirst()
    if let first = arguments.first, !first.hasPrefix("--") {
        options.mode = first
        arguments = arguments.dropFirst()
    }
    var iterator = arguments.makeIterator()
    while let flag = iterator.next() {
        let value = iterator.next() ?? ""
        switch flag {
        case "--minutes": options.minutes = Double(value) ?? options.minutes
        case "--threshold": options.threshold = Double(value) ?? options.threshold
        case "--window": options.window = Double(value) ?? options.window
        case "--pitch-axis": options.pitchAxis = value
        case "--yaw-axis": options.yawAxis = value
        default:
            fputs("Unknown option \(flag)\n", stderr)
            exit(1)
        }
    }
    guard ["count", "calibrate", "log"].contains(options.mode) else {
        fputs("Usage: motion-spike calibrate | count [--minutes N] | log [options]\n", stderr)
        exit(1)
    }
    return options
}

func component(_ rate: CMRotationRate, _ axis: String) -> Double {
    switch axis {
    case "x": return rate.x
    case "y": return rate.y
    default: return rate.z
    }
}

/// Plan v1 detector: a swing past the threshold, then one of the opposite sign within the window.
final class SwingDetector {
    let threshold: Double
    let window: Double
    private var lastSwing: (time: TimeInterval, sign: Double)?
    private var armed = true

    init(threshold: Double, window: Double) {
        self.threshold = threshold
        self.window = window
    }

    /// Feeds one sample; returns true when a gesture completes.
    func feed(_ value: Double, at time: TimeInterval) -> Bool {
        if abs(value) < threshold / 2 {
            armed = true  // hysteresis: one swing counts once
            return false
        }
        guard armed, abs(value) >= threshold else { return false }
        armed = false
        let sign: Double = value > 0 ? 1 : -1
        if let last = lastSwing, last.sign != sign, time - last.time <= window {
            lastSwing = nil
            return true
        }
        lastSwing = (time, sign)
        return false
    }
}

final class Connection: NSObject, CMHeadphoneMotionManagerDelegate {
    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        print("headphones connected")
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        print("headphones disconnected")
    }
}

func describe(_ status: CMAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "not determined (macOS will ask)"
    case .restricted: return "restricted"
    case .denied: return "denied (System Settings → Privacy & Security → Motion & Fitness)"
    case .authorized: return "authorized"
    @unknown default: return "unknown"
    }
}

/// Everything the motion handler touches; only used on `queue`.
final class Session {
    let options: Options
    let queue = OperationQueue()
    let started = Date()
    let nod: SwingDetector
    let shake: SwingDetector
    var samples = 0
    var nods = 0
    var shakes = 0
    var phase = "waiting"  // calibrate: "waiting" until motion flows, then "nod", then "shake"
    var energy: [String: [Double]] = ["nod": [0, 0, 0], "shake": [0, 0, 0]]
    var energySamples: [String: Int] = ["nod": 0, "shake": 0]

    init(options: Options) {
        self.options = options
        queue.maxConcurrentOperationCount = 1
        nod = SwingDetector(threshold: options.threshold, window: options.window)
        shake = SwingDetector(threshold: options.threshold, window: options.window)
    }

    func handle(_ motion: CMDeviceMotion) {
        samples += 1
        let rate = motion.rotationRate
        let time = motion.timestamp
        switch options.mode {
        case "log":
            let a = motion.attitude
            print(String(
                format: "{\"t\":%.4f,\"rx\":%.4f,\"ry\":%.4f,\"rz\":%.4f,"
                    + "\"pitch\":%.4f,\"roll\":%.4f,\"yaw\":%.4f}",
                time, rate.x, rate.y, rate.z, a.pitch, a.roll, a.yaw
            ))
        case "calibrate":
            guard phase != "waiting" else { return }
            energy[phase]?[0] += rate.x * rate.x
            energy[phase]?[1] += rate.y * rate.y
            energy[phase]?[2] += rate.z * rate.z
            energySamples[phase, default: 0] += 1
        default:
            let clock = Date().formatted(date: .omitted, time: .standard)
            if nod.feed(component(rate, options.pitchAxis), at: time) {
                nods += 1
                print("\(clock)  nod #\(nods)")
            }
            if shake.feed(component(rate, options.yawAxis), at: time) {
                shakes += 1
                print("\(clock)  shake #\(shakes)")
            }
        }
    }

    func summary() -> String {
        let minutes = Date().timeIntervalSince(started) / 60
        let perHour = { (count: Int) in minutes > 0 ? Double(count) / minutes * 60 : 0 }
        var lines = [
            String(format: "%.1f min, %ld samples (%.0f Hz)", minutes, samples,
                   minutes > 0 ? Double(samples) / (minutes * 60) : 0),
            String(format: "nods: %ld (%.1f per hour), shakes: %ld (%.1f per hour)",
                   nods, perHour(nods), shakes, perHour(shakes)),
        ]
        // Gestures only count inside 6-second answer windows after tier-1 prompts.
        for prompts in [10.0, 30.0] {
            let share = 6 * prompts / 3600
            lines.append(String(
                format: "  with %.0f tier-1 prompts an hour: about %.2f false nods/hour in windows",
                prompts, perHour(nods) * share
            ))
        }
        return lines.joined(separator: "\n")
    }
}

let options = parseOptions()
let manager = CMHeadphoneMotionManager()
let connection = Connection()
manager.delegate = connection
print("Headphone motion authorization: \(describe(CMHeadphoneMotionManager.authorizationStatus()))")
guard manager.isDeviceMotionAvailable else {
    fputs("Headphone motion isn't available on this Mac (macOS 14+ and supported AirPods).\n", stderr)
    exit(1)
}

let session = Session(options: options)

func finish() {
    manager.stopDeviceMotionUpdates()
    session.queue.addOperation {
        if options.mode == "count" {
            print("\n" + session.summary())
        }
        exit(0)
    }
}

manager.startDeviceMotionUpdates(to: session.queue) { motion, error in
    if let error {
        fputs("motion error: \(error.localizedDescription)\n", stderr)
        return
    }
    if let motion {
        session.handle(motion)
    }
}

signal(SIGINT, SIG_IGN)
let interrupt = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
interrupt.setEventHandler { finish() }
interrupt.resume()

switch options.mode {
case "calibrate":
    // The AirPods' motion stream can take a few seconds to settle (it connects and disconnects at
    // first), so the countdown starts only once samples arrive.
    print("Waiting for head motion from the AirPods…")
    func startCalibration() {
        print("Motion is flowing. Nod five times now (8 s)…")
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) {
            session.queue.addOperation { session.phase = "shake" }
            print("Now shake your head five times (8 s)…")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 16) {
            manager.stopDeviceMotionUpdates()
            session.queue.addOperation {
                for gesture in ["nod", "shake"] {
                    let sums = session.energy[gesture] ?? [0, 0, 0]
                    let count = Double(max(session.energySamples[gesture] ?? 0, 1))
                    let rms = sums.map { ($0 / count).squareRoot() }
                    let axis = ["x", "y", "z"][rms.firstIndex(of: rms.max() ?? 0) ?? 0]
                    print(String(
                        format: "%@: typical speed x %.2f  y %.2f  z %.2f rad/s → strongest axis %@",
                        gesture, rms[0], rms[1], rms[2], axis
                    ))
                }
                print("Use --pitch-axis for the nod axis and --yaw-axis for the shake axis.")
                exit(0)
            }
        }
    }
    _ = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { timer in
        session.queue.addOperation {
            guard session.phase == "waiting", session.samples > 0 else { return }
            session.phase = "nod"
            DispatchQueue.main.async {
                timer.invalidate()
                startCalibration()
            }
        }
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 30) {
        session.queue.addOperation {
            guard session.phase == "waiting" else { return }
            print("No head motion arrived in 30 s. Are both AirPods in your ears and connected?")
            exit(1)
        }
    }
case "count":
    print(String(format: "Counting for %.0f minutes. Work normally; Ctrl-C stops early.",
                 options.minutes))
    DispatchQueue.main.asyncAfter(deadline: .now() + options.minutes * 60) { finish() }
    _ = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { _ in
        session.queue.addOperation { print("\n" + session.summary() + "\n") }
    }
default:
    break
}

RunLoop.main.run()
