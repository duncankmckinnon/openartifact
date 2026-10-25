# macOS service app

Build with `rtk make desktop`, then open `dist/OpenArtifact.app` in Finder. Building
needs the Xcode Command Line Tools (`xcode-select --install`). Running still needs
Docker Desktop and this checkout. The window uses AppKit and WebKit.

The menu bar icon shows service status and provides Open OpenArtifact, Connect an
Agent, Copy MCP URL, Start / Retry, Stop Service, View Logs, and Quit. Closing the
window keeps the service and menu bar app running. Reopen from the icon or Dock.
Quit stops the app's services before exiting. Force Quit or a crash can leave the
Docker containers running; reopening the app recognizes its instance and resumes
management. No start-at-login helper is installed.

The first launch builds Docker images and can take several minutes. Startup is
asynchronous, so the window can close during the build. Errors appear in the
window and status menu; Start / Retry attempts startup again. View Logs opens
`~/Library/Logs/OpenArtifact/service.log`. Health is checked every five seconds.

## Isolation and data

The desktop app uses `desktop/compose.yml`, project `openartifact-desktop`, and
http://127.0.0.1:18765. Only the application port is published, on loopback.
Postgres and Chrome are private to the Compose network. Development services on
8765 and 5432 are independent and are never stopped by the app.

Artifacts live in `~/Library/Application Support/OpenArtifact/store`. The
instance identifier is beside it in `instance.txt`. Database and cache data use
the `openartifact-desktop_postgres` and `openartifact-desktop_cache` Docker volumes.
Stop and Quit preserve all data. This is a new local workspace; artifacts from
the original prototype remain in the development stack at port 8765.

If an existing OpenArtifact service occupies the desktop address with a different
instance identifier, the app attaches as a viewer. It does not pass its credential
to that service, take over its containers, or enable Stop. Use the existing
server's browser sign-in and MCP setup instead. Choosing arbitrary hosted server
URLs is future work.

## Connect an agent

Choose Connect an Agent from the menu bar or press Command-K. Copy Claude Code
Setup produces a user-scoped HTTP MCP command. Copy Codex Config produces a TOML
entry for `~/.codex/config.toml`. Review any existing `openartifact` entry before
adding it. The app never modifies agent configuration files automatically.

Test Connection performs authenticated MCP initialization and tool discovery,
then closes the test session. It does not edit artifacts. The MCP endpoint is
http://127.0.0.1:18765/mcp/. Agents executing on this Mac can reach it; remote web
connectors need a reachable hosted service or a separate connection mechanism.

The built-in chat is optional. The isolated desktop stack does not inherit shell
provider keys; use an external agent for this iteration. Provider settings in the
app are future work.

## Credential boundary

On first launch the app generates a 256-bit random access credential and stores
it in Keychain. The backend receives it at runtime and identifies both MCP calls
and the native viewer as the same local user. The native app exchanges a bearer
header for an HttpOnly, SameSite browser session, held in a nonpersistent WebKit
store. The development sign-in is disabled in desktop mode. The credential is
absent from the web configuration endpoint, HTML, injected scripts and URLs.
Only native controls can copy the private setup snippets.

Copied snippets contain the credential and persist wherever the user pastes
them. Docker administrators can inspect container environment values. This is a
local-user boundary, not isolation from malware running as that user. Authored
HTML is active content served on the application's origin and can act with the
viewer's browser permissions; opening untrusted artifact code requires further
content isolation. No credential rotation UI is included yet.

## Verification

Backend tests cover bearer-only sign-in, rejected credentials and cross-site
requests, disabled desktop sign-in on hosted servers, matching MCP identity, and
absence of the credential from browser configuration. For the native lifecycle:

1. Launch, wait for Running and verify the local workspace opens without login.
2. Open Connect an Agent and run Test Connection.
3. Close the viewer and verify the MCP endpoint still responds.
4. Reopen the viewer, stop the service, and start it again.
5. Quit and confirm only `openartifact-desktop` containers stop.
6. Reopen and confirm the same workspace and credential still work.

Remaining standalone packaging work: bundle Python, Postgres, Git and Chrome;
handle database upgrades and backups; add native downloads, an icon, signing and
notarization. This iteration is still a development app tied to its checkout.
