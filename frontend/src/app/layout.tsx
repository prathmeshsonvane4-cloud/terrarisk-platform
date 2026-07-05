import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TerraRisk AI — Intelligent Terrain & Risk Analytics",
  description:
    "TerraRisk AI delivers deep-learning powered terrain analysis and geospatial risk intelligence for infrastructure, insurance, and environmental decision-making.",
  keywords: [
    "TerraRisk",
    "AI",
    "terrain analysis",
    "geospatial risk",
    "deep tech",
    "climate risk",
  ],
  openGraph: {
    title: "TerraRisk AI — Intelligent Terrain & Risk Analytics",
    description:
      "Deep-learning powered terrain analysis and geospatial risk intelligence.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
