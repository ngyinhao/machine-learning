import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs";

const sourceFiles = ["agents.py", "warehouse.py", "fleet.py", "fulfillment.py", "dashboard_api.py", "site_bridge.py"];
let runtime;

async function startTrainingEngine() {
  const [python, sources] = await Promise.all([
    loadPyodide(),
    Promise.all(sourceFiles.map(async (filename) => {
      const response = await fetch(new URL(filename, import.meta.url));
      if (!response.ok) throw new Error(`Could not load ${filename} (${response.status}).`);
      return response.text();
    })),
  ]);
  sourceFiles.forEach((filename, index) => python.FS.writeFile(filename, sources[index]));
  python.runPython("from site_bridge import dispatch_json");
  return python.globals.get("dispatch_json");
}

self.addEventListener("message", async ({ data: { id, action, payload } }) => {
  try {
    runtime ??= startTrainingEngine();
    const dispatch = await runtime;
    self.postMessage({ id, ...JSON.parse(dispatch(action, JSON.stringify(payload))) });
  } catch (error) {
    self.postMessage({ id, error: "The browser could not load the training engine." });
    console.error(error);
  }
});
