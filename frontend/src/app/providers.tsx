"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { AuthProvider } from "@/features/auth/auth-context";
import { queryClient } from "@/lib/api/query-client";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
