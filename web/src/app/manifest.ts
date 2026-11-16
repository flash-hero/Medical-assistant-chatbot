import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Ausculta",
    short_name: "Ausculta",
    description: "Health information that listens, and shows its sources.",
    start_url: "/en",
    display: "standalone",
    background_color: "#f8fbf9",
    theme_color: "#0e5e44",
    icons: [
      { src: "/brand/ausculta-app-icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/brand/ausculta-app-icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/brand/ausculta-app-icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
