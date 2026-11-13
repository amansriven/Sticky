// Draws Sticky's app icon at every size macOS needs and packs AppIcon.icns.
//   swift app/icon/make-icon.swift OUTPUT_DIR
// Concept "taped switch": a macOS-style permission switch held ON with a strip
// of masking tape, on a dark squircle. Sticky makes permissions stay on.
// (app/icon/concepts.swift draws the alternatives that were considered.)
import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
let iconset = URL(fileURLWithPath: out).appendingPathComponent("AppIcon.iconset")
try? FileManager.default.removeItem(at: iconset)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
let S: CGFloat = 1024

func color(_ hex: UInt32, _ a: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
            blue: CGFloat(hex & 0xff) / 255, alpha: a)
}

func withShadow(_ c: NSColor, blur: CGFloat, y: CGFloat, _ draw: () -> Void) {
    NSGraphicsContext.saveGraphicsState()
    let sh = NSShadow(); sh.shadowColor = c; sh.shadowBlurRadius = blur; sh.shadowOffset = NSSize(width: 0, height: y)
    sh.set(); draw()
    NSGraphicsContext.restoreGraphicsState()
}

func rotated(around p: NSPoint, degrees: CGFloat, _ draw: () -> Void) {
    NSGraphicsContext.saveGraphicsState()
    let t = NSAffineTransform()
    t.translateX(by: p.x, yBy: p.y); t.rotate(byDegrees: degrees); t.translateX(by: -p.x, yBy: -p.y)
    t.concat(); draw()
    NSGraphicsContext.restoreGraphicsState()
}

let body = NSRect(x: 100, y: 100, width: 824, height: 824)
let squircle = NSBezierPath(roundedRect: body, xRadius: 185, yRadius: 185)

func background(_ top: UInt32, _ bottom: UInt32) {
    withShadow(color(0x000000, 0.30), blur: 26, y: -12) { color(0x000000).setFill(); squircle.fill() }
    NSGradient(colors: [color(top), color(bottom)])!.draw(in: squircle, angle: -90)
    NSGraphicsContext.saveGraphicsState(); squircle.addClip()
    NSGradient(colors: [color(0xffffff, 0.14), color(0xffffff, 0)])!
        .draw(in: NSRect(x: body.minX, y: body.midY + 120, width: body.width, height: body.height / 2 - 120), angle: -90)
    NSGraphicsContext.restoreGraphicsState()
}

/// A macOS-style switch in the ON position. Returns the knob's centre.
@discardableResult
func toggle(center: NSPoint, width: CGFloat, height: CGFloat) -> NSPoint {
    let track = NSRect(x: center.x - width / 2, y: center.y - height / 2, width: width, height: height)
    let trackPath = NSBezierPath(roundedRect: track, xRadius: height / 2, yRadius: height / 2)
    withShadow(color(0x000000, 0.25), blur: 18, y: -8) { color(0x30D158).setFill(); trackPath.fill() }
    NSGradient(colors: [color(0x4CE06C), color(0x28B84A)])!.draw(in: trackPath, angle: -90)
    // Inner top shine.
    NSGraphicsContext.saveGraphicsState(); trackPath.addClip()
    NSGradient(colors: [color(0xffffff, 0.22), color(0xffffff, 0)])!
        .draw(in: NSRect(x: track.minX, y: track.midY, width: track.width, height: track.height / 2), angle: -90)
    NSGraphicsContext.restoreGraphicsState()
    let inset = height * 0.08
    let d = height - inset * 2
    let knob = NSRect(x: track.maxX - inset - d, y: track.minY + inset, width: d, height: d)
    withShadow(color(0x000000, 0.30), blur: 14, y: -6) { color(0xffffff).setFill(); NSBezierPath(ovalIn: knob).fill() }
    NSGradient(colors: [color(0xffffff), color(0xE9ECF2)])!.draw(in: NSBezierPath(ovalIn: knob), angle: -90)
    return NSPoint(x: knob.midX, y: knob.midY)
}

/// A strip of masking tape with torn ends.
func tape(center: NSPoint, width: CGFloat, length: CGFloat, degrees: CGFloat) {
    rotated(around: center, degrees: degrees) {
        let r = NSRect(x: center.x - width / 2, y: center.y - length / 2, width: width, height: length)
        let path = NSBezierPath()
        let teeth = 7
        path.move(to: NSPoint(x: r.minX, y: r.minY))
        for i in 1...teeth {   // torn bottom edge
            let x = r.minX + r.width * CGFloat(i) / CGFloat(teeth)
            path.line(to: NSPoint(x: x - r.width / CGFloat(teeth * 2), y: r.minY + (i % 2 == 0 ? 10 : -6)))
            path.line(to: NSPoint(x: x, y: r.minY))
        }
        path.line(to: NSPoint(x: r.maxX, y: r.maxY))
        for i in stride(from: teeth - 1, through: 0, by: -1) {   // torn top edge
            let x = r.minX + r.width * CGFloat(i) / CGFloat(teeth)
            path.line(to: NSPoint(x: x + r.width / CGFloat(teeth * 2), y: r.maxY + (i % 2 == 0 ? -8 : 7)))
            path.line(to: NSPoint(x: x, y: r.maxY))
        }
        path.close()
        withShadow(color(0x000000, 0.22), blur: 10, y: -4) { color(0xF3E3BD, 0.93).setFill(); path.fill() }
        NSGraphicsContext.saveGraphicsState(); path.addClip()
        NSGradient(colors: [color(0xFFF6DF, 0.55), color(0xE6D2A2, 0.25)])!.draw(in: r, angle: 0)
        color(0x8A6D3B, 0.06).setStroke()
        for k in stride(from: r.minY, to: r.maxY, by: 16) {   // paper fibre
            let l = NSBezierPath(); l.move(to: NSPoint(x: r.minX, y: k)); l.line(to: NSPoint(x: r.maxX, y: k + 6))
            l.lineWidth = 2; l.stroke()
        }
        NSGraphicsContext.restoreGraphicsState()
    }
}


/// Draw the icon in a 1024-point space, scaled to `pixels`.
func draw(pixels: Int) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current?.imageInterpolation = .high
    let scale = NSAffineTransform()
    scale.scale(by: CGFloat(pixels) / S)
    scale.concat()
    background(0x2E3342, 0x141722)
    let knob = toggle(center: NSPoint(x: 512, y: 500), width: 600, height: 320)
    tape(center: NSPoint(x: knob.x - 10, y: knob.y + 4), width: 150, length: 430, degrees: -24)
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

for base in [16, 32, 128, 256, 512] {
    for factor in [1, 2] {
        let name = factor == 1 ? "icon_\(base)x\(base).png" : "icon_\(base)x\(base)@2x.png"
        try draw(pixels: base * factor).representation(using: .png, properties: [:])!
            .write(to: iconset.appendingPathComponent(name))
    }
}
let icns = URL(fileURLWithPath: out).appendingPathComponent("AppIcon.icns").path
let p = Process()
p.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
p.arguments = ["-c", "icns", iconset.path, "-o", icns]
try p.run()
p.waitUntilExit()
try? FileManager.default.removeItem(at: iconset)
print(icns)
