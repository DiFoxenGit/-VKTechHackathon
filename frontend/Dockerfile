FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=$VITE_API_URL
ARG VITE_APP_BASE_PATH=/
ENV VITE_APP_BASE_PATH=$VITE_APP_BASE_PATH
ARG NODE_OPTIONS=--max-old-space-size=512
RUN NODE_OPTIONS="$NODE_OPTIONS" npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
