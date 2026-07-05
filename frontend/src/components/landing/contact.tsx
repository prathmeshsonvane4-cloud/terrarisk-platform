"use client";

import { useState } from "react";
import { Mail, MapPin, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export function Contact() {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitted(true);
  }

  return (
    <section id="contact" className="border-t border-border/60 bg-muted/30 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-accent">
            Get in Touch
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
            Ready to de-risk your terrain?
          </h2>
          <p className="mt-4 text-muted-foreground">
            Tell us about your use case and we&apos;ll schedule a personalized
            demo of the TerraRisk platform.
          </p>
        </div>

        <div className="mt-16 grid gap-8 lg:grid-cols-5">
          <div className="space-y-6 lg:col-span-2">
            <Card className="border-border/60">
              <CardHeader>
                <CardTitle className="text-base">Contact Information</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-start gap-3">
                  <Mail className="mt-0.5 size-5 text-primary" />
                  <div>
                    <p className="text-sm font-medium">Email</p>
                    <a
                      href="mailto:hello@terrarisk.ai"
                      className="text-sm text-muted-foreground hover:text-primary"
                    >
                      hello@terrarisk.ai
                    </a>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <MapPin className="mt-0.5 size-5 text-primary" />
                  <div>
                    <p className="text-sm font-medium">Headquarters</p>
                    <p className="text-sm text-muted-foreground">
                      San Francisco, CA
                      <br />
                      United States
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/60 bg-gradient-to-br from-terra-blue/5 to-terra-green/5">
              <CardHeader>
                <CardTitle className="text-base">Enterprise Plans</CardTitle>
                <CardDescription>
                  Custom deployments, on-premise options, and dedicated support
                  for large-scale operations.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>

          <Card className="border-border/60 lg:col-span-3">
            <CardHeader>
              <CardTitle>Request a Demo</CardTitle>
              <CardDescription>
                Fill out the form and our team will respond within one business
                day.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {submitted ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="flex size-14 items-center justify-center rounded-full bg-terra-green/10">
                    <Send className="size-6 text-accent" />
                  </div>
                  <h3 className="mt-4 text-lg font-semibold">Message sent!</h3>
                  <p className="mt-2 max-w-sm text-sm text-muted-foreground">
                    Thank you for your interest in TerraRisk AI. We&apos;ll be
                    in touch shortly.
                  </p>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-5">
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="name">Full Name</Label>
                      <Input id="name" name="name" placeholder="Jane Smith" required />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="email">Work Email</Label>
                      <Input
                        id="email"
                        name="email"
                        type="email"
                        placeholder="jane@company.com"
                        required
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="company">Company</Label>
                    <Input
                      id="company"
                      name="company"
                      placeholder="Acme Infrastructure"
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="message">How can we help?</Label>
                    <Textarea
                      id="message"
                      name="message"
                      placeholder="Describe your terrain risk use case..."
                      rows={4}
                      required
                    />
                  </div>
                  <Button type="submit" className="w-full sm:w-auto">
                    Send Message
                    <Send className="size-4" />
                  </Button>
                </form>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </section>
  );
}
