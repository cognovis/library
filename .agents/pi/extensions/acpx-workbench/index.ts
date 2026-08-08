import { pathToFileURL } from "node:url";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type ExtensionModule = {
  default?: (pi: ExtensionAPI) => Promise<void> | void;
};

export default async function register(pi: ExtensionAPI): Promise<void> {
  const implementationPath = process.env.COGNOVIS_PI_PROVIDER_IMPLEMENTATION_PATH;
  if (!implementationPath) {
    throw new Error(
      "COGNOVIS_PI_PROVIDER_IMPLEMENTATION_PATH is required by the workbench extension",
    );
  }
  const implementation = (await import(pathToFileURL(implementationPath).href)) as ExtensionModule;
  if (typeof implementation.default !== "function") {
    throw new Error("The workbench provider implementation has no default registration function");
  }
  await implementation.default(pi);
}
