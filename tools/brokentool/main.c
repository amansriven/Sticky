/*
 * BrokenTool: a deliberately fragile app for testing Sticky.
 *
 * It's ad-hoc signed, so its identity is a hash of this exact build. Each
 * mode exercises one permission, to see what macOS does after a rebuild:
 *
 *   (no argument)  Automation: ask Finder for its window count via osascript.
 *                  Week 3 result: a rebuild kept the grant (Sticky's R5).
 *   ax             Accessibility: check AXIsProcessTrusted (asking macOS to
 *                  prompt if not trusted), then actually use it by reading
 *                  the focused app. Reports whether each step worked.
 *
 * BUILD_TAG is baked in so every build has a different hash.
 */
#include <ApplicationServices/ApplicationServices.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef BUILD_TAG
#define BUILD_TAG "dev"
#endif

static int automation(void) {
    printf("BrokenTool build %s asking Finder...\n", BUILD_TAG);
    fflush(stdout);
    int rc = system("/usr/bin/osascript -e 'tell application \"Finder\" to count windows'");
    printf("osascript exit status: %d\n", WEXITSTATUS(rc));
    return WEXITSTATUS(rc);
}

static int accessibility(void) {
    printf("BrokenTool build %s checking Accessibility...\n", BUILD_TAG);

    const void *keys[] = {kAXTrustedCheckOptionPrompt};
    const void *values[] = {kCFBooleanTrue};
    CFDictionaryRef options = CFDictionaryCreate(
        NULL, keys, values, 1, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    Boolean trusted = AXIsProcessTrustedWithOptions(options);
    CFRelease(options);
    printf("AXIsProcessTrusted: %s\n", trusted ? "yes" : "no");

    /* Actually use the permission: read which app is frontmost. */
    AXUIElementRef system_wide = AXUIElementCreateSystemWide();
    CFTypeRef app = NULL;
    AXError err = AXUIElementCopyAttributeValue(system_wide, kAXFocusedApplicationAttribute, &app);
    printf("Read focused app via Accessibility: %s (AXError %d)\n",
           err == kAXErrorSuccess ? "worked" : "FAILED", (int)err);
    if (app) CFRelease(app);
    CFRelease(system_wide);
    return trusted && err == kAXErrorSuccess ? 0 : 3;
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "ax") == 0) return accessibility();
    return automation();
}
