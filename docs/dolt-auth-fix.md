# Dolt Persistent Auth (CL-6cl)

**Implementation:** `~/Library/LaunchAgents/com.cognovis.dolt-auth.plist` (created + loaded).
At login: reads `~/.dolt-remote-password`, calls `launchctl setenv DOLT_REMOTE_PASSWORD`,
restarts brew dolt daemon. Daemon then authenticates persistently via its env.

Skill updated: `core:dolt` → "Persistent Auth Setup" section.

If `bd dolt push` fails after reboot: see `core:dolt` skill → "Persistent Auth Setup".
