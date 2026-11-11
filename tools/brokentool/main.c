/*
 * BrokenTool: a deliberately fragile app for testing Sticky.
 *
 * It asks Finder for something via osascript, which needs Automation
 * permission. It's ad-hoc signed, so its identity is a hash of this exact
 * build: rebuild it and macOS treats it as a new app and asks again. That's
 * Sticky's R1b diagnosis ("the app's signing identity changed").
 *
 * BUILD_TAG is baked in so every build has a different hash.
 */
#include <stdio.h>
#include <stdlib.h>

#ifndef BUILD_TAG
#define BUILD_TAG "dev"
#endif

int main(void) {
    printf("BrokenTool build %s asking Finder...\n", BUILD_TAG);
    fflush(stdout);
    int rc = system("/usr/bin/osascript -e 'tell application \"Finder\" to count windows'");
    printf("osascript exit status: %d\n", WEXITSTATUS(rc));
    return WEXITSTATUS(rc);
}
