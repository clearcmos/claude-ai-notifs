// claude-announce-summarize: one-shot prompt against Apple's on-device
// foundation model (Apple Intelligence), used by claude-announce for either a
// constrained Stop assessment or a one-line pending-input summary.
//
// Usage:
//   claude-announce-summarize --check
//       Prints AVAILABLE or UNAVAILABLE: <reason>. Exit 0 when available,
//       4 otherwise. Used by setup.sh to report Apple Intelligence status.
//   claude-announce-summarize <instructions> <prompt>
//       Prints a free-form model response (used for pending-input notices).
//   claude-announce-summarize --assess <instructions> <prompt>
//       Prints a structured JSON assessment for conservative Stop notices.
//
// Requires macOS 26+ and Apple Intelligence enabled in System Settings.
// Compiled by setup.sh with swiftc from the Xcode Command Line Tools.

import Foundation
import FoundationModels

// Use the runtime schema API instead of @Generable macros. The macOS command
// line SDK exposes FoundationModels to swiftc but does not always ship the
// FoundationModelsMacros compiler plugin; DynamicGenerationSchema gives the
// same constrained response shape without requiring that plugin.
func makeAssessmentSchema() throws -> GenerationSchema {
    let text = DynamicGenerationSchema(type: String.self)
    let status = DynamicGenerationSchema(
        name: "TurnStatus",
        description: "The narrowest status explicitly supported by the report",
        anyOf: [
            "changed", "investigated", "answered", "proposed", "verified",
            "blocked", "failed", "unknown",
        ]
    )
    let assessment = DynamicGenerationSchema(
        name: "TurnAssessment",
        description: "A conservative, extractively grounded turn assessment",
        properties: [
            .init(
                name: "evidence",
                description: "Exact words from the report proving the status; empty for unknown",
                schema: text
            ),
            .init(name: "status", schema: status),
            .init(
                name: "topic",
                description: "Exact two-to-eight-word noun phrase from the report; no outcome verb",
                schema: text
            ),
        ]
    )
    return try GenerationSchema(root: assessment, dependencies: [])
}

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

        let assess = args.count == 4 && args[1] == "--assess"
        guard args.count == 3 || assess else {
            FileHandle.standardError.write(
                Data("usage: claude-announce-summarize --check | [--assess] <instructions> <prompt>\n".utf8))
            exit(2)
        }

        guard case .available = model.availability else {
            FileHandle.standardError.write(Data("model unavailable\n".utf8))
            exit(4)
        }

        let instructions = assess ? args[2] : args[1]
        let prompt = assess ? args[3] : args[2]
        let session = LanguageModelSession(instructions: instructions)
        do {
            if assess {
                let options = GenerationOptions(sampling: .greedy, maximumResponseTokens: 120)
                let response = try await session.respond(
                    to: prompt,
                    schema: makeAssessmentSchema(),
                    options: options
                )
                print(response.content.jsonString)
            } else {
                let options = GenerationOptions(temperature: 0.2, maximumResponseTokens: 60)
                let response = try await session.respond(to: prompt, options: options)
                print(response.content)
            }
        } catch {
            FileHandle.standardError.write(Data("generation failed: \(error)\n".utf8))
            exit(5)
        }
    }
}
