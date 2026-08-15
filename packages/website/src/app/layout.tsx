import type { Metadata } from "next";
import { Geist, Cormorant, JetBrains_Mono } from "next/font/google";
import { SiteHeader } from "@/components/site-header";
import "./globals.css";

const geist = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
});

// Authoritative display serif for the manifesto voice.
const cormorant = Cormorant({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
});

// Ultra-clean monospace for CLI, telemetry, and stamped labels.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Public Intelligence — The machine stays in the room",
  description:
    "A self-hosted, OpenAI-compatible control plane for AI inference on hardware you own. Not a service. Not a network. Yours.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geist.variable} ${cormorant.variable} ${jetbrainsMono.variable} dark h-full antialiased`}
    >
      <body className="min-h-full">
        <SiteHeader />
        {children}
      </body>
    </html>
  );
}
