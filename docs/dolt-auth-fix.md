# Dolt Remote Auth Fix (CL-6cl)

## Problem
The brew-managed dolt SQL server (`~/Library/LaunchAgents/homebrew.mxcl.dolt.plist`)
doesn't inherit `DOLT_REMOTE_PASSWORD` from the shell environment at boot. This causes
`bd dolt push` to fail after reboot with:
`must set DOLT_REMOTE_PASSWORD environment variable to use --user param`

## Solution
A dedicated user LaunchAgent (`com.cognovis.dolt-auth`) sets `DOLT_REMOTE_PASSWORD`
via `launchctl setenv` and restarts dolt at login. The password is stored in
`~/.dolt-remote-password` (chmod 600).

## Files Created
- `~/Library/LaunchAgents/com.cognovis.dolt-auth.plist` — sets env + restarts dolt at login
- `~/.dolt-remote-password` — password file (chmod 600)

## Documentation
Core:dolt skill "Auth Layers" section updated with persistent setup instructions.
See: `/Users/malte/code/claude-code-plugins/core/skills/dolt/SKILL.md` (commit a507623)
