FROM node:22-slim

ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=${VITE_API_URL}

WORKDIR /app
COPY package.json package-lock.json /app/
RUN npm ci
COPY . /app
RUN npm run build
EXPOSE 5173
