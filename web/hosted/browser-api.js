"use strict";

(() => {
  const worker = new Worker(new URL("training-worker.mjs", document.currentScript.src), { type: "module" });
  const pending = new Map();
  let nextId = 0;
  let failure;

  worker.addEventListener("message", ({ data: { id, result, error } }) => {
    const request = pending.get(id);
    if (!request) return;
    pending.delete(id);
    if (error) request.reject(new Error(error));
    else request.resolve(result);
  });

  worker.addEventListener("error", () => {
    failure = new Error("The browser could not start the training engine.");
    for (const request of pending.values()) request.reject(failure);
    pending.clear();
    worker.terminate();
  });

  window.warehouseRequest = (action, payload = null) => {
    if (failure) return Promise.reject(failure);
    return new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      worker.postMessage({ id, action, payload });
    });
  };
})();
