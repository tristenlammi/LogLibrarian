FROM node:18-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:alpine

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom nginx config with Docker DNS resolver for dynamic backend IP resolution
COPY nginx.conf /etc/nginx/conf.d/default.conf

# nginx:alpine runs as root but spawns workers as 'nginx' user
# For extra security, we can run as nginx user entirely by adjusting config
# The default nginx.conf already handles this properly

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
