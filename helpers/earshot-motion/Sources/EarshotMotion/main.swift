// earshot-motion: the signed helper for earshotd (Earshot Phase 2, milestone 7; D-016, D-018).
//
//   earshot-motion --socket PATH --token-file PATH [--headset AirPods]
//
// It connects to earshotd's helper socket, proves itself with the shared token, and then:
// - captures the headset's mic while asked, as 16 kHz mono 16-bit samples, so macOS grants the
//   mic once, to this app, instead of to whichever Python runs the daemon
// - streams the head's rotation rate from Core Motion while asked, for shakes and nods
// - reports the default output and input devices whenever they change
// Messages are JSON lines both ways; see src/earshot/voice/helper.py. If the daemon goes away,
// it stops everything and reconnects every two seconds.

import AVFoundation
import CoreAudio
import CoreMotion
import Foundation

struct Options {
    var socket = ""
    var tokenFile = ""
    var headset = "AirPods"
}

func parseOptions() -> Options {
    var options = Options()
    var iterator = CommandLine.arguments.dropFirst().makeIterator()
    while let flag = iterator.next() {
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
                if self.fd < 0, self.connect() {
                    self.send(["hello": "earshot-motion", "v": 1, "token": self.token])
                    DispatchQueue.main.async { self.onConnected?() }
                    self.readUntilClosed()
                    DispatchQueue.main.async { self.onDisconnected?() }
                }
                Thread.sleep(forTimeInterval: 2)
            }
        }
    }

    private func connect() -> Bool {
        let sock = socket(AF_UNIX, SOCK_STREAM, 0)
        guard sock >= 0 else { return false }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        guard bytes.count < MemoryLayout.size(ofValue: address.sun_path) else {
            close(sock)
            return false
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
            return false
        }
        var on: Int32 = 1
        setsockopt(sock, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        fd = sock
        return true
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
        guard var data = try? JSONSerialization.data(withJSONObject: message) else { return }
        data.append(0x0A)
        writes.async {
            guard self.fd >= 0 else { return }
            data.withUnsafeBytes { raw in
                var offset = 0
                while offset < raw.count {
                    let written = write(self.fd, raw.baseAddress! + offset, raw.count - offset)
                    if written <= 0 { return }
                    offset += written
                }
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

// MARK: - The helper

final class Helper {
    let options: Options
    let link: Link
    let engine = AVAudioEngine()
    let motion = CMHeadphoneMotionManager()
    let motionQueue = OperationQueue()
    var micOn = false

    init(options: Options, token: String) {
        self.options = options
        self.link = Link(path: options.socket, token: token)
    }

    func run() {
        link.onConnected = { [weak self] in
            self?.reportPermissions()
            self?.reportDevices()
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
        link.connectForever()
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

    // The headset's mic, converted to 16 kHz mono 16-bit, sent in the buffers the engine gives.
    func setMic(_ on: Bool) {
        guard on != micOn else { return }
        micOn = on
        if !on {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            return
        }
        if let device = allDevices().first(where: {
            deviceName($0).localizedCaseInsensitiveContains(options.headset) && hasInput($0)
        }), let unit = engine.inputNode.audioUnit {
            var id = device
            AudioUnitSetProperty(
                unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &id,
                UInt32(MemoryLayout<AudioDeviceID>.size))
        }
        let input = engine.inputNode.outputFormat(forBus: 0)
        guard let target = AVAudioFormat(
            commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true),
            let converter = AVAudioConverter(from: input, to: target)
        else {
            link.send(["permission": ["mic": "unavailable"]])
            micOn = false
            return
        }
        engine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: input) { [weak self] buffer, _ in
            let frames = AVAudioFrameCount(Double(buffer.frameLength) * 16_000 / input.sampleRate) + 16
            guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: frames) else { return }
            var consumed = false
            var error: NSError?
            converter.convert(to: out, error: &error) { _, status in
                if consumed {
                    status.pointee = .noDataNow
                    return nil
                }
                consumed = true
                status.pointee = .haveData
                return buffer
            }
            guard error == nil, out.frameLength > 0, let samples = out.int16ChannelData else { return }
            let data = Data(bytes: samples[0], count: Int(out.frameLength) * 2)
            self?.link.send(["audio": data.base64EncodedString()])
        }
        do {
            try engine.start()
        } catch {
            engine.inputNode.removeTap(onBus: 0)
            micOn = false
            link.send(["permission": ["mic": "unavailable"]])
        }
    }

    // Rotation rate, in rad/s: x is pitch (nodding), z is yaw (shaking), from Step 0.
    func setMotion(_ on: Bool) {
        if !on {
            motion.stopDeviceMotionUpdates()
            return
        }
        guard motion.isDeviceMotionAvailable, !motion.isDeviceMotionActive else { return }
        motion.startDeviceMotionUpdates(to: motionQueue) { [weak self] sample, _ in
            guard let sample else { return }
            let rate = sample.rotationRate
            self?.link.send(["motion": [sample.timestamp, rate.x, rate.y, rate.z]])
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
