// Draws icon concepts side by side for choosing.
//   swift app/icon/concepts.swift OUTPUT_DIR
import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
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

func pin(at p: NSPoint) {
    // needle shadow + head
    let head = NSRect(x: p.x - 62, y: p.y - 40, width: 124, height: 124)
    withShadow(color(0x000000, 0.35), blur: 16, y: -12) {
        color(0xE5383B).setFill(); NSBezierPath(ovalIn: head).fill()
    }
    NSGradient(colors: [color(0xFF6B6B), color(0xC1121F)])!.draw(in: NSBezierPath(ovalIn: head), angle: -60)
    color(0xffffff, 0.55).setFill()
    NSBezierPath(ovalIn: NSRect(x: head.minX + 28, y: head.maxY - 52, width: 34, height: 22)).fill()
}

func render(_ name: String, _ draw: () -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(S), pixelsHigh: Int(S), bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(out)/\(name).png"))
    return rep
}

let center = NSPoint(x: 512, y: 500)
let a = render("concept-a-taped-switch") {
    background(0x2E3342, 0x141722)
    let knob = toggle(center: center, width: 600, height: 320)
    tape(center: NSPoint(x: knob.x - 10, y: knob.y + 4), width: 150, length: 430, degrees: -24)
}
let b = render("concept-b-sticky-note") {
    background(0x5BA8FF, 0x2F5BEA)
    let note = NSRect(x: 230, y: 220, width: 564, height: 564)
    rotated(around: NSPoint(x: 512, y: 502), degrees: -7) {
        withShadow(color(0x0B1E66, 0.40), blur: 30, y: -18) { color(0xFFD84D).setFill(); NSBezierPath(rect: note).fill() }
        NSGradient(colors: [color(0xFFE780), color(0xFFCE33)])!.draw(in: note, angle: -90)
        color(0xE0B000, 0.25).setFill()   // adhesive strip
        NSBezierPath(rect: NSRect(x: note.minX, y: note.maxY - 90, width: note.width, height: 90)).fill()
        toggle(center: NSPoint(x: note.midX, y: note.midY - 30), width: 380, height: 204)
    }
}
let c = render("concept-c-pinned-switch") {
    background(0xF7F4EE, 0xE4DED2)
    let knob = toggle(center: center, width: 620, height: 330)
    pin(at: NSPoint(x: knob.x, y: knob.y - 6))
}

// Side-by-side sheet, with a small-size row to judge legibility.
let sheet = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1560, pixelsHigh: 700, bitsPerSample: 8,
                             samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                             bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: sheet)
color(0xECECEC).setFill(); NSBezierPath(rect: NSRect(x: 0, y: 0, width: 1560, height: 700)).fill()
for (i, (rep, label)) in [(a, "A  Taped switch"), (b, "B  Sticky note"), (c, "C  Pinned switch")].enumerated() {
    let x = CGFloat(40 + i * 510)
    let img = NSImage(size: NSSize(width: S, height: S)); img.addRepresentation(rep)
    img.draw(in: NSRect(x: x, y: 200, width: 460, height: 460))
    for (j, size) in [64, 32, 16].enumerated() {   // Dock / list / menu sizes
        img.draw(in: NSRect(x: x + 120 + CGFloat(j) * 100, y: 110 - CGFloat(size) / 2, width: CGFloat(size), height: CGFloat(size)))
    }
    (label as NSString).draw(at: NSPoint(x: x + 150, y: 30),
                             withAttributes: [.font: NSFont.systemFont(ofSize: 30, weight: .semibold),
                                              .foregroundColor: NSColor.black])
}
NSGraphicsContext.restoreGraphicsState()
try! sheet.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(out)/concepts.png"))
print("\(out)/concepts.png")
