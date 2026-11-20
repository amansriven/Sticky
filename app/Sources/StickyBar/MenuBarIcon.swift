import AppKit

/// The menu bar icon: the app icon's taped-ON switch, drawn as a template
/// image so macOS tints it for light, dark and highlighted menu bars.
///
/// - `.recording`: switch on, taped down.
/// - `.problem`: the same, with a badge dot (something needs attention).
/// - `.stopped`: the tape is off and the switch is off (not recording).
/// - `.error`: switch off with a badge (Sticky can't read its report).
enum MenuBarIcon: String, CaseIterable {
    case recording, problem, stopped, error

    static let size = NSSize(width: 24, height: 16)

    func image() -> NSImage {
        let image = NSImage(size: Self.size, flipped: false) { _ in
            draw()
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = accessibilityLabel
        return image
    }

    var accessibilityLabel: String {
        switch self {
        case .recording: return "Sticky: recording"
        case .problem: return "Sticky: a problem needs attention"
        case .stopped: return "Sticky: not recording"
        case .error: return "Sticky: can't read the report"
        }
    }

    private var isOn: Bool { self == .recording || self == .problem }
    private var hasBadge: Bool { self == .problem || self == .error }

    private func draw() {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        NSColor.black.setFill()
        NSColor.black.setStroke()

        // Track: a capsule outline, vertically centered, leaving room for the badge.
        let line: CGFloat = 1.5
        let track = NSRect(x: 1, y: 2.5, width: 20, height: 11)
        let trackPath = NSBezierPath(roundedRect: track.insetBy(dx: line / 2, dy: line / 2),
                                     xRadius: (track.height - line) / 2, yRadius: (track.height - line) / 2)
        trackPath.lineWidth = line
        trackPath.stroke()

        // Knob: solid, right when on, left when off.
        let knobD: CGFloat = 7
        let knobX = isOn ? track.maxX - 2 - knobD : track.minX + 2
        let knob = NSRect(x: knobX, y: track.midY - knobD / 2, width: knobD, height: knobD)
        NSBezierPath(ovalIn: knob).fill()

        // Tape: a strip across the knob, cut out of the switch with a gap so it
        // reads as a separate layer, then filled semi-opaque.
        if isOn {
            let center = NSPoint(x: knob.midX, y: knob.midY)
            let tape = tapePath(center: center, length: 12, width: 3)
            ctx.saveGState()
            ctx.setBlendMode(.clear)
            tapePath(center: center, length: 12, width: 3 + 2).fill()
            ctx.restoreGState()
            NSColor.black.withAlphaComponent(0.55).setFill()
            tape.fill()
            NSColor.black.setFill()
        }

        // Badge: a dot at the top right, with a clear ring around it.
        if hasBadge {
            let d: CGFloat = 5.5
            let dot = NSRect(x: Self.size.width - d - 0.25, y: Self.size.height - d - 0.25, width: d, height: d)
            ctx.saveGState()
            ctx.setBlendMode(.clear)
            NSBezierPath(ovalIn: dot.insetBy(dx: -1.5, dy: -1.5)).fill()
            ctx.restoreGState()
            NSBezierPath(ovalIn: dot).fill()
        }
    }

    /// A strip tilted like the app icon's tape (-24°).
    private func tapePath(center: NSPoint, length: CGFloat, width: CGFloat) -> NSBezierPath {
        let path = NSBezierPath(rect: NSRect(x: -length / 2, y: -width / 2, width: length, height: width))
        var t = AffineTransform(translationByX: center.x, byY: center.y)
        t.rotate(byDegrees: -24)
        path.transform(using: t)
        return path
    }
}
