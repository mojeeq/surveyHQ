# ---- Build the static bundle ----
FROM node:22-alpine AS build

# The repository layout is kept inside the image rather than flattened, because
# the build reaches above the frontend directory: `npm run build` renders the
# documentation in docs/ into the in-app help through ../scripts/build-help.mjs,
# and that relative path has to still be true here. The build context is the
# repository root; see the web service in docker-compose.yml.
WORKDIR /repo/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Above the frontend, and copied before the application source so that editing
# a component does not re-copy the documentation.
COPY docs /repo/docs
COPY scripts/build-help.mjs /repo/scripts/build-help.mjs

COPY frontend/ ./
RUN npm run build

# ---- Serve it, and proxy the API ----
# Dynamic upstream DNS requires nginx 1.27.3 or newer.
FROM nginx:1.27.5-alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY frontend/nginx.conf /etc/nginx/conf.d/surveyhq.conf
COPY --from=build /repo/frontend/dist /usr/share/nginx/html

EXPOSE 80

# 127.0.0.1 rather than localhost. Inside the container localhost resolves to
# ::1 first, nginx above listens on IPv4 only, and busybox wget does not fall
# back to the second address - so this reported "connection refused" on a
# container that was serving every request put to it. It had never passed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
