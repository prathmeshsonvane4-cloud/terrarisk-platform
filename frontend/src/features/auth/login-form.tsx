"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { useAuth } from "./auth-context";
import { useLogin } from "./use-login";

/** Reads ?next= set by the auth guard before it bounced an unauthenticated
 * visit to /login (M2B P7 deep-link preservation) — plain browser API
 * rather than useSearchParams() so this page needs no Suspense boundary.
 * Only ever a same-origin path: an absolute/external `next` value is
 * rejected to prevent an open-redirect via a crafted login link. */
function getPostLoginPath(): string {
  if (typeof window === "undefined") return "/";
  const next = new URLSearchParams(window.location.search).get("next");
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { login } = useAuth();
  const router = useRouter();
  const loginMutation = useLogin();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    loginMutation.mutate(
      { email, password },
      {
        onSuccess: (data) => {
          if (!data) return;
          login({ token: data.access_token, role: data.role, fullName: data.full_name });
          router.replace(getPostLoginPath());
        },
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {loginMutation.isError && (
        <p role="alert" className="text-sm text-destructive">
          {loginMutation.error.message}
        </p>
      )}
      <Button type="submit" size="lg" className="mt-2 w-full" disabled={loginMutation.isPending}>
        {loginMutation.isPending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
