// earshot-motion: the signed helper for earshotd (Earshot Phase 2, milestone 7; D-016, D-018).
//
//   earshot-motion --socket PATH --token-file PATH [--headset AirPods] [--stem]
//
// It connects to earshotd's helper socket, proves itself with the shared token, and then:
// - captures the headset's mic while asked, as 16 kHz mono 16-bit samples, so macOS grants the
//   mic once, to this app, instead of to whichever Python runs the daemon
// - streams the head's rotation rate from Core Motion while asked, for shakes and nods
// - reports the default output and input devices whenever they change
// - with --stem, becomes the "Now Playing" app, so a press of the AirPods stem (play/pause)
//   reaches it, and sends {"button": "stem"} for push-to-talk (D-032)
// - asks for both permissions when it starts, so neither prompt arrives in the middle of a request
// - starts the mic again if capture stops under it (a device change), and says so in a "log"
//   message
// Messages are JSON lines both ways; see src/earshot/voice/helper.py. If the daemon goes away,
// it stops everything and reconnects every two seconds.

import AVFoundation
import CoreAudio
import CoreMotion
import Foundation
import MediaPlayer

struct Options {
    var socket = ""
    var tokenFile = ""
    var headset = "AirPods"
    var stem = false
}

func parseOptions() -> Options {
    var options = Options()
    var iterator = CommandLine.arguments.dropFirst().makeIterator()
    while let flag = iterator.next() {
        if flag == "--stem" {
            options.stem = true
            continue
        }
        let value = iterator.next() ?? ""
        switch flag {
        case "--socket": options.socket = value
        case "--token-file": options.tokenFile = value
        case "--headset": options.headset = value
        default: break  // Launch Services may add its own arguments
        }
    }
    return options
}

// MARK: - The link to earshotd

final class Link {
    private let path: String
    private let token: String
    private var fd: Int32 = -1
    private let writes = DispatchQueue(label: "dev.earshot.motion.writes")
    private var buffer = Data()
    var onMessage: (([String: Any]) -> Void)?
    var onConnected: (() -> Void)?
    var onDisconnected: (() -> Void)?

    init(path: String, token: String) {
        self.path = path
        self.token = token
    }

    func connectForever() {
        DispatchQueue.global().async {
            while true {
                if self.fd < 0, let sock = self.connect() {
                    // The hello goes first: nothing else is written until the socket is shared.
                    let hello: [String: Any] = ["hello": "earshot-motion", "v": 1, "token": self.token]
                    self.writes.sync {
                        self.fd = sock
                        self.write(hello)
                    }
                    DispatchQueue.main.async { self.onConnected?() }
                    self.readUntilClosed()
                    DispatchQueue.main.async { self.onDisconnected?() }
                }
                Thread.sleep(forTimeInterval: 2)
            }
        }
    }

    private func connect() -> Int32? {
        let sock = socket(AF_UNIX, SOCK_STREAM, 0)
        guard sock >= 0 else { return nil }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        guard bytes.count < MemoryLayout.size(ofValue: address.sun_path) else {
            close(sock)
            return nil
        }
        withUnsafeMutableBytes(of: &address.sun_path) { raw in
            raw.copyBytes(from: bytes)
        }
        let size = socklen_t(MemoryLayout<sockaddr_un>.size)
        let result = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(sock, $0, size) }
        }
        guard result == 0 else {
            close(sock)
            return nil
        }
        var on: Int32 = 1
        setsockopt(sock, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        return sock
    }

    private func readUntilClosed() {
        var chunk = [UInt8](repeating: 0, count: 4096)
        while fd >= 0 {
            let count = read(fd, &chunk, chunk.count)
            if count <= 0 { break }
            buffer.append(contentsOf: chunk[0..<count])
            while let newline = buffer.firstIndex(of: 0x0A) {
                let line = buffer.subdata(in: buffer.startIndex..<newline)
                buffer.removeSubrange(buffer.startIndex...newline)
                if let message = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                    DispatchQueue.main.async { self.onMessage?(message) }
                }
            }
        }
        writes.sync {
            if fd >= 0 { close(fd) }
            fd = -1
        }
        buffer.removeAll()
    }

    func send(_ message: [String: Any]) {
        writes.async { self.write(message) }
    }

    // On the writes queue only.
    private func write(_ message: [String: Any]) {
        guard fd >= 0, var data = try? JSONSerialization.data(withJSONObject: message) else { return }
        data.append(0x0A)
        data.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                let written = Darwin.write(fd, raw.baseAddress! + offset, raw.count - offset)
                if written <= 0 { return }
                offset += written
            }
        }
    }
}

// MARK: - Devices

func deviceName(_ id: AudioDeviceID) -> String {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioObjectPropertyName,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var name: CFString = "" as CFString
    var size = UInt32(MemoryLayout<CFString>.size)
    let status = withUnsafeMutablePointer(to: &name) {
        AudioObjectGetPropertyData(id, &address, 0, nil, &size, $0)
    }
    return status == noErr ? name as String : ""
}

func defaultDevice(_ selector: AudioObjectPropertySelector) -> AudioDeviceID {
    var address = AudioObjectPropertyAddress(
        mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var id = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &id)
    return id
}

func allDevices() -> [AudioDeviceID] {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDevices, mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(0)
    let system = AudioObjectID(kAudioObjectSystemObject)
    AudioObjectGetPropertyDataSize(system, &address, 0, nil, &size)
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(system, &address, 0, nil, &size, &ids)
    return ids
}

func hasInput(_ id: AudioDeviceID) -> Bool {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyStreams, mScope: kAudioDevicePropertyScopeInput,
        mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(0)
    return AudioObjectGetPropertyDataSize(id, &address, 0, nil, &size) == noErr && size > 0
}

// MARK: - The mic

// Input only, through AVCaptureSession, which converts to 16 kHz mono 16-bit itself.
// AVAudioEngine isn't used: on macOS its input runs through a unit with an output side too, and
// when the AirPods' output is at 48 kHz (music) while their mic is at 24 kHz (a call), it won't
// start at all (error -10868, format not supported).
final class Mic: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    private let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "dev.earshot.motion.mic")
    private let onAudio: (Data) -> Void
    private(set) var chunks = 0
    let device: String

    // Nil when no mic can be opened; `failure` then says why.
    init?(headset: String, onAudio: @escaping (Data) -> Void, failure: inout String) {
        self.onAudio = onAudio
        let found = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified
        ).devices
        guard let chosen = found.first(where: {
            $0.localizedName.localizedCaseInsensitiveContains(headset)
        }) ?? AVCaptureDevice.default(for: .audio) else {
            failure = "no mic found"
            return nil
        }
        device = chosen.localizedName
        super.init()
        do {
            let input = try AVCaptureDeviceInput(device: chosen)
            let output = AVCaptureAudioDataOutput()
            output.audioSettings = [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsNonInterleaved: false,
            ]
            output.setSampleBufferDelegate(self, queue: queue)
            session.beginConfiguration()
            guard session.canAddInput(input), session.canAddOutput(output) else {
                session.commitConfiguration()
                failure = "the capture session refused \(chosen.localizedName)"
                return nil
            }
            session.addInput(input)
            session.addOutput(output)
            session.commitConfiguration()
        } catch {
            failure = "\(chosen.localizedName): \(error.localizedDescription)"
            return nil
        }
    }

    var running: Bool { session.isRunning }
    var captureSession: AVCaptureSession { session }

    func start() { session.startRunning() }  // blocks until running; call off the main thread if it matters
    func stop() { session.stopRunning() }

    func captureOutput(
        _ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let block = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }
        let length = CMBlockBufferGetDataLength(block)
        guard length > 0 else { return }
        var data = Data(count: length)
        let status = data.withUnsafeMutableBytes { raw in
            CMBlockBufferCopyDataBytes(
                block, atOffset: 0, dataLength: length, destination: raw.baseAddress!)
        }
        guard status == kCMBlockBufferNoErr else { return }
        chunks += 1
        onAudio(data)
    }
}

// MARK: - The helper

final class Helper {
    let options: Options
    let link: Link
    let motion = CMHeadphoneMotionManager()
    let motionQueue = OperationQueue()
    var mic: Mic?
    var micOn: Bool { mic != nil }
    var motionWanted = false
    var motionSeen = false

    init(options: Options, token: String) {
        self.options = options
        self.link = Link(path: options.socket, token: token)
    }

    func run() {
        link.onConnected = { [weak self] in
            self?.reportPermissions()
            self?.reportDevices()
            if self?.options.stem == true {
                self?.link.send(["log": "listening for the stem (play/pause) as the Now Playing app"])
            }
        }
        link.onDisconnected = { [weak self] in
            self?.setMic(false)
            self?.setMotion(false)
        }
        link.onMessage = { [weak self] message in
            if let on = message["mic"] as? Bool { self?.setMic(on) }
            if let on = message["motion"] as? Bool { self?.setMotion(on) }
        }
        for selector in [kAudioHardwarePropertyDefaultOutputDevice,
                         kAudioHardwarePropertyDefaultInputDevice, kAudioHardwarePropertyDevices] {
            var address = AudioObjectPropertyAddress(
                mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                mElement: kAudioObjectPropertyElementMain)
            AudioObjectAddPropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject), &address, DispatchQueue.main
            ) { [weak self] _, _ in self?.reportDevices() }
        }
        AVCaptureDevice.requestAccess(for: .audio) { [weak self] _ in
            DispatchQueue.main.async { self?.reportPermissions() }
        }
        for name in [AVCaptureSession.runtimeErrorNotification,
                     AVCaptureSession.wasInterruptedNotification] {
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) {
                [weak self] note in
                guard let self, let mic = self.mic, (note.object as AnyObject?) === mic.captureSession
                else { return }
                self.audioSetupChanged(note.name.rawValue)
            }
        }
        askForMotion()
        listenForMuteGesture()
        if options.stem { listenForStem() }
        link.connectForever()
    }

    // While the mic is open, a press of the AirPods stem is macOS's mute gesture, not play/pause.
    // An app that captures without handling it gets "Cannot Control Mic with AirPods" on screen.
    // The helper handles it and never mutes: Earshot's mic stays live for the answer, and with
    // --stem the press is passed on like any other (the daemon ignores presses during an
    // approval, D-032).
    func listenForMuteGesture() {
        do {
            try AVAudioApplication.shared.setInputMuteStateChangeHandler { [weak self] _ in
                DispatchQueue.main.async {
                    guard let self else { return }
                    try? AVAudioApplication.shared.setInputMuted(false)
                    self.link.send(["log": "the mute gesture (a stem press with the mic open): mic kept on"])
                    if self.options.stem { self.link.send(["button": "stem"]) }
                }
                return true
            }
        } catch {
            link.send(["log": "couldn't take the mute gesture: \(error.localizedDescription)"])
        }
    }

    // The AirPods stem sends the system's play/pause command to the "Now Playing" app. Claiming
    // that role means the stem no longer plays or pauses music while the helper runs, which is
    // why it's opt-in (D-032). Each press, of any kind, is one push-to-talk.
    func listenForStem() {
        let center = MPRemoteCommandCenter.shared()
        for command in [center.togglePlayPauseCommand, center.playCommand, center.pauseCommand,
                        center.nextTrackCommand, center.previousTrackCommand] {
            command.isEnabled = true
            command.addTarget { [weak self] _ in
                self?.link.send(["button": "stem"])
                return .success
            }
        }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: "Earshot",
            MPMediaItemPropertyArtist: "Press the stem to talk",
            MPNowPlayingInfoPropertyPlaybackRate: 0.0,
        ]
        MPNowPlayingInfoCenter.default().playbackState = .playing
    }

    // Core Motion asks for permission the first time it's read. Read it once now, so the prompt
    // comes when the helper starts and not in the middle of a request. The headphones' motion
    // takes a moment to appear after launch, so this tries for ten seconds.
    func askForMotion(tries: Int = 20) {
        guard CMHeadphoneMotionManager.authorizationStatus() == .notDetermined, !motionWanted
        else { return }
        guard motion.isDeviceMotionAvailable else {
            if tries > 0 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                    self?.askForMotion(tries: tries - 1)
                }
            }
            return
        }
        guard !motion.isDeviceMotionActive else { return }
        motion.startDeviceMotionUpdates(to: motionQueue) { [weak self] _, _ in
            DispatchQueue.main.async {
                guard let self, !self.motionWanted else { return }
                self.motion.stopDeviceMotionUpdates()
                self.reportPermissions()
            }
        }
    }

    // A device change can stop capture under it: start the mic again.
    func audioSetupChanged(_ why: String) {
        guard let old = mic, !old.running else { return }
        setMic(false)
        setMic(true)
        link.send(["log": "the mic stopped (\(why)): \(micOn ? "started again" : "lost")"])
    }

    func reportDevices() {
        let output = deviceName(defaultDevice(kAudioHardwarePropertyDefaultOutputDevice))
        let input = deviceName(defaultDevice(kAudioHardwarePropertyDefaultInputDevice))
        let headset = allDevices().contains {
            deviceName($0).localizedCaseInsensitiveContains(options.headset) && hasInput($0)
        }
        link.send(["devices": ["output": output, "input": input, "headset": headset]])
    }

    func reportPermissions() {
        let mic: String
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: mic = "granted"
        case .denied, .restricted: mic = "denied"
        default: mic = "not asked"
        }
        let motionStatus: String
        switch CMHeadphoneMotionManager.authorizationStatus() {
        case .authorized: motionStatus = "granted"
        case .denied, .restricted: motionStatus = "denied"
        default: motionStatus = "not asked"
        }
        link.send(["permission": ["mic": mic, "motion": motionStatus]])
    }

    // The headset's mic, as 16 kHz mono 16-bit samples, sent in the buffers capture gives.
    func setMic(_ on: Bool) {
        guard on != micOn else { return }
        if !on {
            if let old = mic {
                mic = nil
                old.stop()
                link.send(["log": "mic off: \(old.chunks) chunks sent"])
            }
            return
        }
        var failure = ""
        guard let new = Mic(headset: options.headset, onAudio: { [weak self] data in
            self?.link.send(["audio": data.base64EncodedString()])
        }, failure: &failure) else {
            link.send(["log": "mic failed: \(failure)"])
            link.send(["permission": ["mic": "unavailable"]])
            return
        }
        mic = new
        new.start()
        if new.running {
            link.send(["log": "mic on: \(new.device), captured at 16000 Hz"])
        } else {
            mic = nil
            link.send(["log": "mic failed to start: \(new.device)"])
            link.send(["permission": ["mic": "unavailable"]])
        }
    }

    // Rotation rate, in rad/s: x is pitch (nodding), z is yaw (shaking), from Step 0.
    func setMotion(_ on: Bool) {
        motionWanted = on
        motion.stopDeviceMotionUpdates()  // also ends the read that only asked for permission
        guard on, motion.isDeviceMotionAvailable else { return }
        motion.startDeviceMotionUpdates(to: motionQueue) { [weak self] sample, _ in
            guard let self, let sample else { return }
            let rate = sample.rotationRate
            self.link.send(["motion": [sample.timestamp, rate.x, rate.y, rate.z]])
            if !self.motionSeen {  // the first sample ever: the permission is settled now
                self.motionSeen = true
                DispatchQueue.main.async { self.reportPermissions() }
            }
        }
    }
}

let options = parseOptions()
guard !options.socket.isEmpty,
      let token = try? String(contentsOfFile: options.tokenFile, encoding: .utf8)
else {
    fputs("usage: earshot-motion --socket PATH --token-file PATH [--headset NAME]\n", stderr)
    exit(64)
}
let helper = Helper(options: options, token: token.trimmingCharacters(in: .whitespacesAndNewlines))
helper.run()
RunLoop.main.run()
