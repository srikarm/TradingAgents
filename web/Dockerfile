FROM node:20-alpine AS base
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV NEXTAUTH_SECRET=build-time-dummy-secret-replaced-at-runtime
ENV AUTH_GITHUB_ID=dummy
ENV AUTH_GITHUB_SECRET=dummy
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start"]
