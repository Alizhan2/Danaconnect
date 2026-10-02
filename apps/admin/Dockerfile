FROM node:22-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/admin/package.json apps/admin/package-lock.json ./
RUN npm ci
COPY apps/admin/ ./
ARG API_BASE_URL=http://api:8000
ARG ADMIN_BASE_PATH=/admin
ARG NEXT_PUBLIC_WEB_URL
ENV API_BASE_URL=$API_BASE_URL ADMIN_BASE_PATH=$ADMIN_BASE_PATH NEXT_PUBLIC_WEB_URL=$NEXT_PUBLIC_WEB_URL
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3001
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3001
CMD ["node", "server.js"]
