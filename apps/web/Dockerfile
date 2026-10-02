FROM node:22-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
ARG API_BASE_URL=http://api:8000
ARG ADMIN_APP_URL
ARG NEXT_PUBLIC_WEB_URL
ENV API_BASE_URL=$API_BASE_URL ADMIN_APP_URL=$ADMIN_APP_URL NEXT_PUBLIC_WEB_URL=$NEXT_PUBLIC_WEB_URL
RUN mkdir -p public && npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
