import {
  BarChart3,
  Brain,
  Layers,
  MapPin,
  Satellite,
  Zap,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const features = [
  {
    icon: Satellite,
    title: "Multi-source Data Fusion",
    description:
      "Ingest satellite, drone, LiDAR, and ground sensor data into a unified geospatial pipeline with automated quality checks.",
  },
  {
    icon: Brain,
    title: "Deep Learning Models",
    description:
      "Proprietary neural networks trained on millions of terrain samples deliver sub-meter risk predictions at scale.",
  },
  {
    icon: Layers,
    title: "3D Terrain Reconstruction",
    description:
      "Generate high-fidelity digital elevation models and slope stability maps from sparse or noisy input data.",
  },
  {
    icon: MapPin,
    title: "Real-time Monitoring",
    description:
      "Continuous anomaly detection alerts your team to ground movement, erosion, and hydrological changes as they occur.",
  },
  {
    icon: BarChart3,
    title: "Risk Scoring Engine",
    description:
      "Quantify exposure across portfolios with customizable risk indices aligned to insurance and engineering standards.",
  },
  {
    icon: Zap,
    title: "API-first Integration",
    description:
      "Embed TerraRisk intelligence into GIS platforms, underwriting workflows, and construction management tools via REST API.",
  },
];

export function Features() {
  return (
    <section id="features" className="border-t border-border/60 bg-muted/30 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-accent">
            Platform Capabilities
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
            Everything you need to assess terrain risk
          </h2>
          <p className="mt-4 text-muted-foreground">
            From raw geospatial data to boardroom-ready insights — one platform
            built for engineers, insurers, and climate analysts.
          </p>
        </div>

        <div className="mt-16 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <Card
              key={feature.title}
              className="border-border/60 bg-card transition-shadow hover:shadow-md"
            >
              <CardHeader>
                <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-gradient-to-br from-terra-blue/10 to-terra-green/10">
                  <feature.icon className="size-5 text-primary" />
                </div>
                <CardTitle>{feature.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-sm leading-relaxed">
                  {feature.description}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
