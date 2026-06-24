import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/apple-touch-icon.png", "icons/favicon.svg"],
      manifest: {
        name: "Swing Trader",
        short_name: "Swing",
        description: "추천 종목 watchlist · 추천가 vs 현재가",
        lang: "ko",
        theme_color: "#0b0e13",
        background_color: "#0b0e13",
        display: "standalone",
        orientation: "portrait",
        scope: "/",
        start_url: "/",
        icons: [
          { src: "icons/pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/pwa-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "icons/maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        navigateFallback: "index.html",
        globPatterns: ["**/*.{js,css,html,svg,png,woff,woff2}"],
        runtimeCaching: [
          {
            // Recommendation feed (data branch via raw GitHub).
            urlPattern: /^https:\/\/raw\.githubusercontent\.com\/.*\/feed\.json.*$/,
            handler: "NetworkFirst",
            options: {
              cacheName: "feed",
              networkTimeoutSeconds: 6,
              expiration: { maxEntries: 4, maxAgeSeconds: 60 * 60 * 24 },
            },
          },
          {
            // Live quotes from the Cloudflare Worker proxy.
            urlPattern: /\/quote\?/,
            handler: "NetworkFirst",
            options: {
              cacheName: "quotes",
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 8, maxAgeSeconds: 60 * 5 },
            },
          },
          {
            // Full analysis reports (GitHub Pages) shown in the detail iframe.
            urlPattern: /^https:\/\/[a-z0-9-]+\.github\.io\/.*\.html$/,
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "reports",
              expiration: { maxEntries: 40, maxAgeSeconds: 60 * 60 * 24 * 7 },
            },
          },
          {
            urlPattern: /^https:\/\/(cdn\.jsdelivr\.net|fonts\.gstatic\.com|fonts\.googleapis\.com)\/.*$/,
            handler: "CacheFirst",
            options: {
              cacheName: "fonts",
              expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 * 365 },
            },
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
});
