import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Il bundle finisce dentro il componente: è ciò che Home Assistant serve come
// percorso statico, e ciò che HACS distribuisce. Un file solo, nome fisso e
// nessun chunk: il pannello lo carica come modulo ESM da un url noto, e la
// cache si invalida con la query `?v=<versione>` messa da panel.py.
export default defineConfig({
  plugins: [react()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    outDir: "../custom_components/ctha/frontend",
    emptyOutDir: true,
    target: "es2022",
    cssCodeSplit: false,
    rollupOptions: {
      input: "src/main.tsx",
      output: {
        format: "es",
        entryFileNames: "ctha-panel.js",
        inlineDynamicImports: true,
      },
    },
  },
});
