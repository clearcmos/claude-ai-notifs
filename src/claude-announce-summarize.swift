// claude-announce-summarize: one-shot prompt against Apple's on-device
// foundation model (Apple Intelligence), used by claude-announce to compress
// a Claude Code turn into a single spoken sentence.
//
// Usage:
//   claude-announce-summarize --check
//       Prints AVAILABLE or UNAVAILABLE: <reason>. Exit 0 when available,
//       4 otherwise. Used by setup.sh to report Apple Intelligence status.
//   claude-announce-summarize <instructions> <prompt>
//       Prints the model response to stdout. Exit 0 on success; any other
//       exit code means the caller should fall back (claude -p, then ding).
//
// Requires macOS 26+ and Apple Intelligence enabled in System Settings.
// Compiled by setup.sh with swiftc from the Xcode Command Line Tools.

import Foundation
import FoundationModels

@main
struct Summarize {
    static func main() async {
        let args = CommandLine.arguments

        guard #available(macOS 26.0, *) else {
            FileHandle.standardError.write(Data("macOS 26 or later required\n".utf8))
            exit(3)
        }

        let model = SystemLanguageModel.default

        if args.count == 2 && args[1] == "--check" {
            switch model.availability {
            case .available:
                print("AVAILABLE")
                exit(0)
            case .unavailable(let reason):
                print("UNAVAILABLE: \(reason)")
                exit(4)
            }
        }

        guard args.count == 3 else {
            FileHandle.standardError.write(
                Data("usage: claude-announce-summarize --check | <instructions> <prompt>\n".utf8))
            exit(2)
        }

        guard case .available = model.availability else {
            FileHandle.standardError.write(Data("model unavailable\n".utf8))
            exit(4)
        }

        let session = LanguageModelSession(instructions: args[1])
        do {
            let options = GenerationOptions(temperature: 0.2, maximumResponseTokens: 60)
            let response = try await session.respond(to: args[2], options: options)
            print(response.content)
        } catch {
            FileHandle.standardError.write(Data("generation failed: \(error)\n".utf8))
            exit(5)
        }
    }
}
