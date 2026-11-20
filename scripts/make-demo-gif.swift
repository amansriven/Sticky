// Assembles the README demo GIF from a real terminal session and real app
// snapshots: BrokenTool is rebuilt and silently refused Accessibility, the
// menu shows the problem, and the app page explains it.
//
//   swift scripts/make-demo-gif.swift TERMINAL.txt MENU.png APP.png OUT.gif [--scale 1.5]
//
// TERMINAL.txt is the session as shown: lines starting with "$ " are typed
// commands, the rest is their output (with your home folder shown as ~).
// MENU.png and APP.png come from `StickyBar --snapshot` (2x). Writes an
// animated GIF with ImageIO, so it needs nothing beyond macOS.
//
// Making the inputs (all real; the recorder must be running):
//   1. tools/brokentool/build.sh demo, then tools/brokentool/run.sh ax.
//      BrokenTool needs an earlier build approved for Accessibility, so the
//      new build is refused silently. Save both commands' output.
//   2. Copy the database and keep only BrokenTool, Claude Code and Apple
//      services, as for the README screenshots; set STICKY_DB to the copy.
//   3. With STICKY_BIN=$PWD/scripts/sticky-dev, from the bundled app
//      (app/build.sh) so the menu shows the app icon:
//        app/build/Sticky.app/Contents/MacOS/StickyBar --snapshot DIR --page menu
//        app/build/Sticky.app/Contents/MacOS/StickyBar --snapshot DIR \
//            --page app:dev.sticky.brokentool --size 840x520
import AppKit
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count >= 5 else {
    print("usage: make-demo-gif.swift TERMINAL.txt MENU.png APP.png OUT.gif [--scale S]")
    exit(2)
}
let terminalLines = try! String(contentsOfFile: args[1], encoding: .utf8)
    .split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
    .filter { !$0.isEmpty }
let menu = NSImage(contentsOfFile: args[2])!
let app = NSImage(contentsOfFile: args[3])!
let output = args[4]
let scale = args.firstIndex(of: "--scale").map { CGFloat(Double(args[$0 + 1])!) } ?? 1.5

// Layout in points; the GIF is `scale` pixels per point.
let canvas = CGSize(width: 960, height: 640)
let captionHeight: CGFloat = 64
let background = NSColor(srgbRed: 0.20, green: 0.24, blue: 0.30, alpha: 1)

func pixels(_ image: NSImage) -> CGSize {
    let rep = image.representations.first!
    return CGSize(width: rep.pixelsWide, height: rep.pixelsHigh)
}

/// A rect given from the top-left, converted to AppKit's bottom-left origin.
func top(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> NSRect {
    NSRect(x: x, y: canvas.height - y - h, width: w, height: h)
}

// MARK: Drawing pieces

func drawShadowed(_ shape: NSBezierPath, alpha: CGFloat = 0.45) {
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(alpha)
    shadow.shadowBlurRadius = 22
    shadow.shadowOffset = NSSize(width: 0, height: -8)
    shadow.set()
    NSColor.black.setFill()
    shape.fill()
    NSGraphicsContext.restoreGraphicsState()
}

/// A window with a title bar, traffic lights and `content` drawn below the bar.
func drawWindow(_ frame: NSRect, title: String, dark: Bool, alpha: CGFloat = 1,
                content: (NSRect) -> Void) {
    let bar: CGFloat = 28
    let shape = NSBezierPath(roundedRect: frame, xRadius: 10, yRadius: 10)
    let ctx = NSGraphicsContext.current!.cgContext
    NSGraphicsContext.saveGraphicsState()
    ctx.setAlpha(alpha)
    ctx.beginTransparencyLayer(auxiliaryInfo: nil)
    drawShadowed(shape)
    NSGraphicsContext.saveGraphicsState()
    shape.addClip()
    (dark ? NSColor(white: 0.12, alpha: 1) : NSColor(white: 0.96, alpha: 1)).setFill()
    shape.fill()
    (dark ? NSColor(white: 0.19, alpha: 1) : NSColor(white: 0.92, alpha: 1)).setFill()
    NSBezierPath(rect: NSRect(x: frame.minX, y: frame.maxY - bar, width: frame.width, height: bar)).fill()
    for (i, hex) in [0xFF5F57, 0xFEBC2E, 0x28C840].enumerated() {
        NSColor(srgbRed: CGFloat(hex >> 16) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
                blue: CGFloat(hex & 0xff) / 255, alpha: 1).setFill()
        NSBezierPath(ovalIn: NSRect(x: frame.minX + 12 + CGFloat(i) * 20, y: frame.maxY - bar / 2 - 6,
                                    width: 12, height: 12)).fill()
    }
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 13, weight: .semibold),
        .foregroundColor: dark ? NSColor(white: 0.75, alpha: 1) : NSColor(white: 0.3, alpha: 1)]
    let size = (title as NSString).size(withAttributes: attrs)
    (title as NSString).draw(at: NSPoint(x: frame.midX - size.width / 2, y: frame.maxY - bar / 2 - size.height / 2),
                             withAttributes: attrs)
    content(NSRect(x: frame.minX, y: frame.minY, width: frame.width, height: frame.height - bar))
    NSGraphicsContext.restoreGraphicsState()
    (dark ? NSColor(white: 1, alpha: 0.14) : NSColor(white: 0, alpha: 0.14)).setStroke()
    shape.lineWidth = 1
    shape.stroke()
    ctx.endTransparencyLayer()
    NSGraphicsContext.restoreGraphicsState()
}

let mono = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
let monoBold = NSFont.monospacedSystemFont(ofSize: 11, weight: .semibold)

/// The terminal window showing the first `count` lines.
func drawTerminal(lines count: Int) {
    let frame = top(24, 170, 700, 232)
    drawWindow(frame, title: "zsh", dark: true) { area in
        var y = area.maxY - 14
        let shown = Array(terminalLines.prefix(count))
        for (i, line) in shown.enumerated() {
            let text = NSMutableAttributedString()
            if line.hasPrefix("$ ") {
                text.append(NSAttributedString(string: "$ ", attributes: [
                    .font: monoBold, .foregroundColor: NSColor(srgbRed: 0.45, green: 0.85, blue: 0.5, alpha: 1)]))
                text.append(NSAttributedString(string: String(line.dropFirst(2)), attributes: [
                    .font: monoBold, .foregroundColor: NSColor(white: 0.95, alpha: 1)]))
            } else {
                let bad = line.contains("FAILED") || line.hasSuffix(": no")
                text.append(NSAttributedString(string: line, attributes: [
                    .font: mono,
                    .foregroundColor: bad ? NSColor(srgbRed: 1, green: 0.42, blue: 0.4, alpha: 1)
                                          : NSColor(white: 0.78, alpha: 1)]))
            }
            y -= 18
            text.draw(at: NSPoint(x: area.minX + 14, y: y))
            // A cursor after the last command while nothing has answered yet.
            if i == shown.count - 1 && line.hasPrefix("$ ") {
                NSColor(white: 0.85, alpha: 1).setFill()
                NSBezierPath(rect: NSRect(x: area.minX + 14 + text.size().width + 2, y: y + 1,
                                          width: 7, height: 14)).fill()
            }
        }
    }
}

/// The menu bar dropdown, hanging from the top right.
func drawMenu(alpha: CGFloat) {
    let px = pixels(menu)
    let size = CGSize(width: px.width / 2, height: px.height / 2)
    let frame = top(canvas.width - size.width - 28, 14, size.width, size.height)
    let shape = NSBezierPath(roundedRect: frame, xRadius: 12, yRadius: 12)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current?.cgContext.setAlpha(alpha)
    NSGraphicsContext.current?.cgContext.beginTransparencyLayer(auxiliaryInfo: nil)
    drawShadowed(shape)
    shape.addClip()
    menu.draw(in: frame)
    NSColor(white: 0, alpha: 0.15).setStroke()
    shape.lineWidth = 1
    shape.stroke()
    NSGraphicsContext.current?.cgContext.endTransparencyLayer()
    NSGraphicsContext.restoreGraphicsState()
}

/// The app window, centered over everything.
func drawApp(alpha: CGFloat) {
    let px = pixels(app)
    let size = CGSize(width: px.width / 2, height: px.height / 2)
    let frame = top((canvas.width - size.width) / 2, 10, size.width, size.height + 28)
    drawWindow(frame, title: "Sticky", dark: false, alpha: alpha) { area in
        app.draw(in: area)
    }
}

func drawCaption(_ text: String) {
    let band = top(0, canvas.height - captionHeight, canvas.width, captionHeight)
    NSColor(white: 0, alpha: 0.35).setFill()
    NSBezierPath(rect: band).fill()
    let para = NSMutableParagraphStyle()
    para.alignment = .center
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 19, weight: .semibold),
        .foregroundColor: NSColor.white, .paragraphStyle: para]
    let size = (text as NSString).size(withAttributes: attrs)
    (text as NSString).draw(in: NSRect(x: band.minX, y: band.midY - size.height / 2, width: band.width,
                                       height: size.height), withAttributes: attrs)
}

// MARK: Frames

struct Frame {
    var seconds: Double
    var terminal: Int
    var menu: CGFloat = 0
    var app: CGFloat = 0
    var caption: String
}

let commands = terminalLines.indices.filter { terminalLines[$0].hasPrefix("$ ") }
let secondCommand = commands.count > 1 ? commands[1] : terminalLines.count
let rebuild = "BrokenTool has Accessibility. Rebuild it…"
let refused = "…and macOS refuses it without asking. System Settings still shows it on."
let notices = "Sticky notices within seconds…"
let explains = "…and explains why, with the fix."

var frames: [Frame] = [
    Frame(seconds: 1.2, terminal: 1, caption: rebuild),
    Frame(seconds: 1.4, terminal: secondCommand, caption: rebuild),
    Frame(seconds: 0.9, terminal: secondCommand + 1, caption: rebuild),
    Frame(seconds: 3.2, terminal: terminalLines.count, caption: refused),
]
for a in [0.35, 0.7] as [CGFloat] {
    frames.append(Frame(seconds: 0.07, terminal: terminalLines.count, menu: a, caption: notices))
}
frames.append(Frame(seconds: 2.6, terminal: terminalLines.count, menu: 1, caption: notices))
for a in [0.25, 0.5, 0.75] as [CGFloat] {
    frames.append(Frame(seconds: 0.07, terminal: terminalLines.count, menu: 1, app: a, caption: explains))
}
frames.append(Frame(seconds: 6.5, terminal: terminalLines.count, menu: 1, app: 1, caption: explains))

// MARK: Render and write

let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: output) as CFURL,
                                           UTType.gif.identifier as CFString, frames.count, nil)!
CGImageDestinationSetProperties(dest, [
    kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary)

for f in frames {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(canvas.width * scale),
                               pixelsHigh: Int(canvas.height * scale), bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = canvas
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current?.imageInterpolation = .high
    background.setFill()
    NSBezierPath(rect: NSRect(origin: .zero, size: canvas)).fill()
    drawTerminal(lines: f.terminal)
    if f.menu > 0 { drawMenu(alpha: f.menu) }
    if f.app > 0 { drawApp(alpha: f.app) }
    drawCaption(f.caption)
    NSGraphicsContext.restoreGraphicsState()
    CGImageDestinationAddImage(dest, rep.cgImage!, [
        kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: f.seconds,
                                        kCGImagePropertyGIFUnclampedDelayTime: f.seconds]] as CFDictionary)
}
guard CGImageDestinationFinalize(dest) else { fatalError("couldn't write \(output)") }
print(output)
