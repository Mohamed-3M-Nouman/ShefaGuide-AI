FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_SUPERVISOR_KEY=shefaguide_supervisor_dev_key
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_SUPERVISOR_KEY=$VITE_SUPERVISOR_KEY
RUN npm run build

FROM node:22-alpine
WORKDIR /app
COPY --from=builder /app ./
EXPOSE 5173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
