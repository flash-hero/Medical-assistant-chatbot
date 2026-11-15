# syntax=docker/dockerfile:1.7
# Ausculta web (Next.js standalone output). Build from the repo root:
#   docker build -f deploy/web.Dockerfile -t ausculta-web .
FROM node:24-alpine AS deps
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:24-alpine AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /web/node_modules ./node_modules
COPY web ./
RUN npm run build

FROM node:24-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
WORKDIR /srv
COPY --from=build --chown=app:app /web/.next/standalone ./
COPY --from=build --chown=app:app /web/.next/static ./.next/static
COPY --from=build --chown=app:app /web/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
