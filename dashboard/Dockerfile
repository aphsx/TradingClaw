FROM node:20-alpine

WORKDIR /app

# ── Accept NEXT_PUBLIC_* vars at build time ───────────────────────────────────
# These get baked into the client-side JS bundle by Next.js.
# Passed via docker-compose build.args (or --build-arg on CLI).
ARG NEXT_PUBLIC_SOCKET_URL=http://localhost:8080
ENV NEXT_PUBLIC_SOCKET_URL=$NEXT_PUBLIC_SOCKET_URL

# ── Install dependencies ──────────────────────────────────────────────────────
COPY package.json package-lock.json* ./
RUN npm install

# ── Copy source (includes .env.local which Next.js uses at build time) ────────
COPY . .

# ── Build Next.js ─────────────────────────────────────────────────────────────
RUN npm run build

EXPOSE 3000
CMD ["npm", "start"]
