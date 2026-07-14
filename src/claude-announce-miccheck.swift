// claude-announce-miccheck: reports whether any process on the system is
// capturing audio input. Microphone in use is the one signal shared by every
// meeting app (Zoom, Google Meet, Teams, Webex, Slack huddles, FaceTime...),
// including while muted, so claude-announce uses it to swap the spoken
// announcement for a silent banner during calls.
//
// Prints "BUSY <bundle ids>" and exits 0 when at least one process has a live
// input stream; prints "IDLE" and exits 1 otherwise. Uses the CoreAudio
// process-object API (macOS 14.4+). Any error reports IDLE, so the caller
// fails toward speaking rather than silently dropping announcements.
//
// Compiled by setup.sh with swiftc, like claude-announce-summarize.

import CoreAudio
import Foundation

func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
}

@available(macOS 14.4, *)
func capturingBundleIDs() -> [String] {
    var addr = address(kAudioHardwarePropertyProcessObjectList)
    var size: UInt32 = 0
    let system = AudioObjectID(kAudioObjectSystemObject)
    guard AudioObjectGetPropertyDataSize(system, &addr, 0, nil, &size) == noErr,
          size > 0 else { return [] }
    var objects = [AudioObjectID](
        repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(system, &addr, 0, nil, &size, &objects) == noErr
    else { return [] }

    var found: [String] = []
    for obj in objects {
        var runAddr = address(kAudioProcessPropertyIsRunningInput)
        var running: UInt32 = 0
        var runSize = UInt32(MemoryLayout<UInt32>.size)
        guard AudioObjectGetPropertyData(obj, &runAddr, 0, nil, &runSize, &running) == noErr,
              running != 0 else { continue }

        var idAddr = address(kAudioProcessPropertyBundleID)
        var bundle: CFString? = nil
        var idSize = UInt32(MemoryLayout<CFString?>.size)
        let status = withUnsafeMutablePointer(to: &bundle) { ptr in
            AudioObjectGetPropertyData(obj, &idAddr, 0, nil, &idSize, ptr)
        }
        let name = (status == noErr ? (bundle as String?) : nil) ?? "unknown"
        found.append(name.isEmpty ? "unknown" : name)
    }
    return found
}

guard #available(macOS 14.4, *) else {
    print("IDLE")
    exit(1)
}
let busy = capturingBundleIDs()
if busy.isEmpty {
    print("IDLE")
    exit(1)
}
print("BUSY " + busy.joined(separator: " "))
exit(0)
