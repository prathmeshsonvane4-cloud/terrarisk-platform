"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/features/auth/auth-context";

export default function RootPage() {
  const { session, isInitialized } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isInitialized) return;
    router.replace(session ? "/farms/new" : "/login");
  }, [isInitialized, session, router]);

  return null;
}
