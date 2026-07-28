"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type CatchmentResponse = components["schemas"]["CatchmentResponse"];

interface UploadCatchmentInput {
  file: File;
  name: string;
  organizationId?: string;
}

/** POST /catchments/upload (file-upload path, M4-004) — no precedent to
 * mirror in this codebase (Service 1 farms are only ever hand-drawn), so
 * this is new UI wiring, built to the same hook shape as every other
 * mutation here. */
export function useUploadCatchment() {
  return useMutation({
    mutationFn: async ({ file, name, organizationId }: UploadCatchmentInput): Promise<CatchmentResponse> => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("name", name);
      if (organizationId) {
        formData.append("organization_id", organizationId);
      }

      const { data, error, response } = await apiClient.POST("/api/v1/catchments/upload", {
        // openapi-fetch's generated type for a multipart body is the
        // documented field-object shape (Body_upload_catchment_...), for
        // API-doc purposes only — the real runtime contract needs an
        // actual FormData instance (defaultBodySerializer only passes a
        // body through unchanged when it's `instanceof FormData`;
        // anything else gets JSON.stringify'd, which FastAPI's File()
        // param can't parse). Same "generated type doesn't match the real
        // runtime contract" situation lib/api/errors.ts already documents
        // for undeclared error responses, applied here to the request side.
        body: formData as unknown as components["schemas"]["Body_upload_catchment_api_v1_catchments_upload_post"],
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
  });
}
