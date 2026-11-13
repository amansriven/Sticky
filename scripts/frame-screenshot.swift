// Frames a snapshot as a macOS window for the README: title bar with traffic
// lights, rounded corners, hairline border, soft shadow, transparent margin.
//   swift scripts/frame-screenshot.swift IN.png OUT.png [--dark] [--title TEXT] [--width PX] [--panel]
// --panel draws a menu-style panel instead (no title bar).
import AppKit

let args = CommandLine.arguments
let input = args[1], output = args[2]
let dark = args.contains("--dark")
let title = args.firstIndex(of: "--title").map { args[$0 + 1] } ?? "Sticky"
let outWidth = args.firstIndex(of: "--width").map { Double(args[$0 + 1])! } ?? 1600

guard let shot = NSImage(contentsOfFile: input), let rep = shot.representations.first else { fatalError("can't read \(input)") }
let px = CGSize(width: rep.pixelsWide, height: rep.pixelsHigh)   // snapshots are 2x
let scale: CGFloat = 2
let panel = args.contains("--panel")
let bar: CGFloat = panel ? 0 : 52 * scale / 2 * 2   // 52 pt title bar
let margin: CGFloat = 70
let radius: CGFloat = 24
let canvas = CGSize(width: px.width + margin * 2, height: px.height + bar + margin * 2)

let out = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(canvas.width), pixelsHigh: Int(canvas.height),
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: out)
let window = NSRect(x: margin, y: margin, width: px.width, height: px.height + bar)
let shape = NSBezierPath(roundedRect: window, xRadius: radius, yRadius: radius)

let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(dark ? 0.55 : 0.28)
shadow.shadowBlurRadius = 46
shadow.shadowOffset = NSSize(width: 0, height: -18)
NSGraphicsContext.saveGraphicsState(); shadow.set()
NSColor.black.setFill(); shape.fill()
NSGraphicsContext.restoreGraphicsState()

NSGraphicsContext.saveGraphicsState(); shape.addClip()
// Title bar.
if !panel {
(dark ? NSColor(white: 0.17, alpha: 1) : NSColor(white: 0.93, alpha: 1)).setFill()
NSBezierPath(rect: NSRect(x: window.minX, y: window.maxY - bar, width: window.width, height: bar)).fill()
for (i, hex) in [0xFF5F57, 0xFEBC2E, 0x28C840].enumerated() {
    NSColor(srgbRed: CGFloat(hex >> 16) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
            blue: CGFloat(hex & 0xff) / 255, alpha: 1).setFill()
    NSBezierPath(ovalIn: NSRect(x: window.minX + 32 + CGFloat(i) * 40, y: window.maxY - bar / 2 - 12,
                                width: 24, height: 24)).fill()
}
let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 26, weight: .semibold),
                                            .foregroundColor: dark ? NSColor(white: 0.85, alpha: 1) : NSColor(white: 0.25, alpha: 1)]
let t = title as NSString
let ts = t.size(withAttributes: attrs)
t.draw(at: NSPoint(x: window.midX - ts.width / 2, y: window.maxY - bar / 2 - ts.height / 2), withAttributes: attrs)
}
// Content.
shot.draw(in: NSRect(x: window.minX, y: window.minY, width: px.width, height: px.height))
NSGraphicsContext.restoreGraphicsState()
// Hairline border.
(dark ? NSColor(white: 1, alpha: 0.12) : NSColor(white: 0, alpha: 0.12)).setStroke()
shape.lineWidth = 2; shape.stroke()
NSGraphicsContext.restoreGraphicsState()

// Downscale for the README.
let ratio = outWidth / canvas.width
let final = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(outWidth), pixelsHigh: Int(canvas.height * ratio),
                             bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                             colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: final)
NSGraphicsContext.current?.imageInterpolation = .high
let full = NSImage(size: canvas); full.addRepresentation(out)
full.draw(in: NSRect(x: 0, y: 0, width: outWidth, height: canvas.height * ratio))
NSGraphicsContext.restoreGraphicsState()
try! final.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: output))
print(output)
