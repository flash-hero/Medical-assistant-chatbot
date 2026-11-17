import type { ReactNode } from "react";

/** The real document lives in [locale]/layout.tsx; this pass-through exists for the global not-found page. */
export default function RootLayout({ children }: { readonly children: ReactNode }) {
  return children;
}
