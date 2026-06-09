import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    // app.js derives backendUrl from location.hostname -> http://localhost:8000;
    // MSW handlers target that origin.
    environmentOptions: { jsdom: { url: "http://localhost:8000/" } },
    setupFiles: ["./test/setup.js"],
    include: ["test/**/*.test.js"],
    restoreMocks: true,
  },
});
