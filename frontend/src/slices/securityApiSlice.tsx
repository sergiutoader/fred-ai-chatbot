// Copyright Thales 2025
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { createApi } from "@reduxjs/toolkit/query/react";

/**
 * Représente la configuration de sécurité exposée par le backend.
 */
export interface SecurityConfig {
  enabled: boolean;
  idp: string;
  issuer: string;
  jwks_url: string;
  client_id: string;
  claims_mapping: Record<string, string>;
}

// ⚠️ Lazy load pour éviter les problèmes de circular import
let baseQuery: any;

(async () => {
  const mod = await import("../common/dynamicBaseQuery.tsx");
  baseQuery = mod.createDynamicBaseQuery({ backend: "api" });
})();

// RTK Slice
export const securityApiSlice = createApi({
  reducerPath: "securityApi",
  baseQuery: async (...args) => {
    if (!baseQuery) {
      const mod = await import("../common/dynamicBaseQuery.tsx");
      baseQuery = mod.createDynamicBaseQuery({ backend: "api" });
    }
    return baseQuery(...args);
  },
  endpoints: (builder) => ({
    getSecurityConfig: builder.query<SecurityConfig, void>({
      query: () => ({
        url: "/agentic/v1/config/security",
        method: "GET",
      }),
    }),
  }),
});

// Hook React (si besoin)
export const {
  useGetSecurityConfigQuery,
} = securityApiSlice;
