import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "VociBot", description: "Local-first clinical documentation assistant" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
