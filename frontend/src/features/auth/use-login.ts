"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";

interface LoginInput {
  email: string;
  password: string;
}

export function useLogin() {
  return useMutation({
    mutationFn: async ({ email, password }: LoginInput) => {
      const { data, error } = await apiClient.POST("/api/v1/auth/login", {
        body: { email, password },
      });
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data;
    },
  });
}
