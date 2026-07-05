import Link from "next/link";
import { ArrowRight, Globe2, Shield, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -top-40 left-1/2 h-[520px] w-[720px] -translate-x-1/2 rounded-full bg-gradient-to-br from-terra-blue/20 via-transparent to-terra-green/20 blur-3xl" />
        <div className="absolute bottom-0 left-0 h-64 w-64 rounded-full bg-terra-green/10 blur-3xl" />
        <div className="absolute right-0 top-1/3 h-72 w-72 rounded-full bg-terra-blue/10 blur-3xl" />
      </div>

      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28 lg:px-8 lg:py-32">
        <div className="mx-auto max-w-3xl text-center">
          <Badge
            variant="secondary"
            className="mb-6 gap-1.5 border border-primary/20 bg-primary/5 px-3 py-1 text-primary"
          >
            <Sparkles className="size-3.5" />
            Deep-tech geospatial intelligence
          </Badge>

          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
            Map terrain risk with{" "}
            <span className="bg-gradient-to-r from-terra-blue to-terra-green bg-clip-text text-transparent">
              precision AI
            </span>
          </h1>

          <p className="mt-6 text-lg leading-relaxed text-muted-foreground sm:text-xl">
            TerraRisk AI transforms satellite imagery, LiDAR, and environmental
            data into actionable risk models — helping teams predict landslides,
            floods, and infrastructure vulnerability before they happen.
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Button size="lg" className="h-11 px-6" render={<Link href="#contact" />}>
              Get Early Access
              <ArrowRight className="size-4" />
            </Button>
            <Button
              variant="outline"
              size="lg"
              className="h-11 px-6"
              render={<Link href="#features" />}
            >
              Explore Platform
            </Button>
          </div>

          <div className="mt-16 grid grid-cols-1 gap-6 sm:grid-cols-3">
            {[
              {
                icon: Globe2,
                stat: "50M+",
                label: "Hectares analyzed",
              },
              {
                icon: Shield,
                stat: "99.2%",
                label: "Model accuracy",
              },
              {
                icon: Sparkles,
                stat: "< 2 min",
                label: "Risk report generation",
              },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-xl border border-border/60 bg-card/50 p-5 backdrop-blur-sm"
              >
                <item.icon className="mx-auto size-6 text-primary" />
                <p className="mt-3 text-2xl font-bold">{item.stat}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {item.label}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
