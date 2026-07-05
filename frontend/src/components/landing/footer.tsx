import Link from "next/link";
import { Mountain } from "lucide-react";

import { Separator } from "@/components/ui/separator";

const footerLinks = {
  Product: [
    { label: "Features", href: "#features" },
    { label: "API Docs", href: "#" },
    { label: "Pricing", href: "#contact" },
  ],
  Company: [
    { label: "About", href: "#about" },
    { label: "Careers", href: "#" },
    { label: "Blog", href: "#" },
  ],
  Legal: [
    { label: "Privacy", href: "#" },
    { label: "Terms", href: "#" },
    { label: "Security", href: "#" },
  ],
};

export function Footer() {
  return (
    <footer className="border-t border-border/60 py-12">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <Link href="/" className="flex items-center gap-2.5">
              <div className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-terra-blue to-terra-green text-white">
                <Mountain className="size-4" />
              </div>
              <span className="font-semibold">
                TerraRisk<span className="text-primary"> AI</span>
              </span>
            </Link>
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted-foreground">
              Intelligent terrain and geospatial risk analytics powered by deep
              learning.
            </p>
          </div>

          {Object.entries(footerLinks).map(([category, links]) => (
            <div key={category}>
              <h3 className="text-sm font-semibold">{category}</h3>
              <ul className="mt-4 space-y-2.5">
                {links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <Separator className="my-8" />

        <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
          <p className="text-sm text-muted-foreground">
            &copy; {new Date().getFullYear()} TerraRisk AI. All rights reserved.
          </p>
          <p className="text-sm text-muted-foreground">
            Built with Next.js · Deploy on{" "}
            <a
              href="https://vercel.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline"
            >
              Vercel
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}
