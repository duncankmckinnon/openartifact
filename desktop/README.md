# macOS prototype

Run `rtk make desktop`, then open `dist/OpenArtifact.app` in Finder. Building needs
the Xcode Command Line Tools (`xcode-select --install`). Running needs Docker
Desktop to be installed and running. No Rust or Node desktop toolchain is needed:
the window uses AppKit and WebKit.

The app runs `docker compose up --build -d --wait` from this checkout, waits for
the health check, and opens http://127.0.0.1:8765 in a native window. The first
launch needs internet access and can take several minutes. Use the development
sign-in on the login page. External links open in your default browser.

This is a development launcher, not a standalone distribution. Keep the checkout
in place, or rebuild after moving it. It shares the existing Compose database,
artifact store (`data/store`), ports and environment configuration. Quit closes
the window but leaves services running; `rtk make down` stops them without
deleting artifacts. Startup output is in
`~/Library/Logs/OpenArtifact/startup.log`. Reopen the app to retry a failed start.
AI chat still requires provider configuration as described in the root README.

Remaining work for a standalone app: package the backend and database, move data
to Application Support, manage service lifetime, support native downloads and
export dialogs, add an icon, and sign and notarize a distributable build. The
prototype uses the existing Chrome container for exports; WebKit is the viewer.
