import { randomUUID } from "node:crypto";
import path from "node:path";

function safeSegment(value: string): string {
  return value.replace(/[^a-zA-Z0-9.-]/g, "_");
}

export interface FusionChildRuntime {
  environment: NodeJS.ProcessEnv;
  sessionId: string;
  stateDirectory?: string;
}

export function createFusionChildRuntime(
  ambient: NodeJS.ProcessEnv,
  role: string,
  persistentSessionId?: string,
  freshId: () => string = randomUUID,
): FusionChildRuntime {
  const parentSessionId = ambient.COGNOVIS_PI_SESSION_ID ?? "fusion";
  const sessionId = `${parentSessionId}-${role.toLowerCase()}-${
    persistentSessionId ?? freshId()
  }`;
  const parentState = ambient.COGNOVIS_PI_ACPX_STATE_DIR;
  const stateDirectory = parentState
    ? path.join(parentState, "fusion-children", safeSegment(sessionId))
    : undefined;
  return {
    sessionId,
    ...(stateDirectory ? { stateDirectory } : {}),
    environment: {
      ...ambient,
      COGNOVIS_PI_SESSION_ID: sessionId,
      ...(stateDirectory
        ? { COGNOVIS_PI_ACPX_STATE_DIR: stateDirectory }
        : {}),
      PI_OFFLINE: "1",
      PI_SKIP_VERSION_CHECK: "1",
    },
  };
}
