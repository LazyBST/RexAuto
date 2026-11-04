// Local OCR with Apple's Vision framework (ships with macOS; nothing is downloaded or sent anywhere).
// usage: ocr <image.png>   -> JSON [{"t": text, "x": left, "y": top, "w": width, "h": height, "c": confidence}] in pixels, per word
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1, let img = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("cannot read image\n".data(using: .utf8)!); exit(2)
}
let W = Double(cg.width), H = Double(cg.height)
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false      // part numbers and codes must not be "corrected"
req.recognitionLanguages = ["en-US"]
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try handler.perform([req])
var out: [[String: Any]] = []
for obs in (req.results ?? []) {
    guard let cand = obs.topCandidates(1).first else { continue }
    let s = cand.string
    var idx = s.startIndex
    while idx < s.endIndex {
        while idx < s.endIndex, s[idx] == " " { idx = s.index(after: idx) }
        if idx >= s.endIndex { break }
        var end = idx
        while end < s.endIndex, s[end] != " " { end = s.index(after: end) }
        let r = idx..<end
        if let box = try? cand.boundingBox(for: r) {
            let b = box.boundingBox
            out.append(["t": String(s[r]), "x": b.minX * W, "y": (1 - b.maxY) * H, "w": b.width * W, "h": b.height * H, "c": cand.confidence])
        }
        idx = end
    }
}
let data = try JSONSerialization.data(withJSONObject: out)
FileHandle.standardOutput.write(data)
