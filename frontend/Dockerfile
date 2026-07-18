# syntax=docker/dockerfile:1

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_ vars are inlined into the client bundle at build time, not
# read at container runtime — this ARG must be declared and exported before
# `next build` runs, or the production bundle silently falls back to the
# dev default baked into src/lib/api/client.ts. Empty string by default:
# nginx (docker/nginx/nginx.conf) proxies /api/ on the same origin, so a
# relative path is correct for the primary deployment path — see
# docs/Deployment_Guide.md for overriding it for a non-nginx setup.
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# output: "standalone" (next.config.ts) traces the minimal server + only the
# node_modules it actually needs — the runner never installs npm packages
# itself, which is most of the image-size saving.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000 HOSTNAME="0.0.0.0"

# 127.0.0.1, not localhost: found during M3 verification — Alpine/musl
# resolves "localhost" to ::1 first, and the standalone server (HOSTNAME=
# "0.0.0.0" above) only binds the IPv4 wildcard, so wget-to-"localhost"
# got a real connection refused despite the server being up and serving
# real responses on 127.0.0.1 the whole time.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
