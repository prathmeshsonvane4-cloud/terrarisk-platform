import { CheckCircle2 } from "lucide-react";

import { Separator } from "@/components/ui/separator";

const values = [
  "Built by geospatial engineers and ML researchers from top institutions",
  "Peer-reviewed methodologies validated against real-world disaster data",
  "SOC 2 compliant infrastructure with end-to-end data encryption",
  "Designed for climate resilience and sustainable infrastructure planning",
];

export function About() {
  return (
    <section id="about" className="py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-primary">
              About TerraRisk AI
            </p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Deep tech for a changing planet
            </h2>
            <p className="mt-6 leading-relaxed text-muted-foreground">
              TerraRisk AI was founded on a simple belief: the world needs
              better tools to understand how terrain behaves under stress. Our
              team combines decades of experience in remote sensing, structural
              engineering, and applied machine learning.
            </p>
            <p className="mt-4 leading-relaxed text-muted-foreground">
              We partner with infrastructure operators, reinsurers, and
              government agencies to turn complex geophysical signals into clear,
              defensible risk assessments — reducing uncertainty when stakes are
              highest.
            </p>

            <Separator className="my-8" />

            <ul className="space-y-3">
              {values.map((value) => (
                <li key={value} className="flex items-start gap-3">
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-accent" />
                  <span className="text-sm leading-relaxed text-muted-foreground">
                    {value}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="relative">
            <div className="aspect-[4/3] overflow-hidden rounded-2xl border border-border/60 bg-gradient-to-br from-terra-blue/20 via-muted to-terra-green/20 p-8 shadow-lg">
              <div className="flex h-full flex-col justify-between rounded-xl border border-white/20 bg-background/60 p-6 backdrop-blur-sm">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Live Risk Dashboard
                  </p>
                  <p className="mt-2 text-2xl font-bold">Sierra Foothills</p>
                  <p className="text-sm text-muted-foreground">
                    California, USA · 12,400 km² coverage
                  </p>
                </div>

                <div className="space-y-4">
                  {[
                    { label: "Landslide Risk", value: 72, color: "bg-amber-500" },
                    { label: "Flood Exposure", value: 45, color: "bg-terra-blue" },
                    { label: "Slope Stability", value: 88, color: "bg-terra-green" },
                  ].map((metric) => (
                    <div key={metric.label}>
                      <div className="mb-1.5 flex justify-between text-sm">
                        <span className="text-muted-foreground">
                          {metric.label}
                        </span>
                        <span className="font-medium">{metric.value}%</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-muted">
                        <div
                          className={`h-full rounded-full ${metric.color}`}
                          style={{ width: `${metric.value}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                <p className="text-xs text-muted-foreground">
                  Updated 4 minutes ago · Model v2.4.1
                </p>
              </div>
            </div>

            <div className="absolute -bottom-4 -left-4 rounded-xl border border-border/60 bg-card px-4 py-3 shadow-md">
              <p className="text-2xl font-bold text-primary">$2.4B</p>
              <p className="text-xs text-muted-foreground">
                Assets under analysis
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
