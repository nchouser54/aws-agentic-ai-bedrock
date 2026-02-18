# Generic Dockerfile for Static Websites
# Works with: HTML, React/Vue/Angular builds, Jekyll, Hugo, etc.
#
# Build Context: Your static site directory (containing index.html, dist/, build/, etc.)
#
# Usage:
#   docker build -t my-static-site .
#   docker run -p 8080:80 my-static-site

FROM public.ecr.aws/nginx/nginx:1.26-alpine

# Optional: Install additional tools if needed
# RUN apk add --no-cache curl

# Copy static files to nginx webroot
# Adjust source path based on your project structure:
#   - For plain HTML: COPY . /usr/share/nginx/html/
#   - For React: COPY build/ /usr/share/nginx/html/
#   - For Vue: COPY dist/ /usr/share/nginx/html/
#   - For Angular: COPY dist/<app-name>/ /usr/share/nginx/html/
#   - For Jekyll/Hugo: COPY _site/ or public/ /usr/share/nginx/html/

COPY . /usr/share/nginx/html/

# Optional: Copy custom nginx configuration
# COPY nginx.conf /etc/nginx/nginx.conf
# COPY default.conf /etc/nginx/conf.d/default.conf

# Create custom nginx config for Single Page Applications (SPA)
# Uncomment if you need SPA routing support (React Router, Vue Router, etc.)
RUN echo 'server { \
    listen 80; \
    server_name _; \
    root /usr/share/nginx/html; \
    index index.html index.htm; \
    \
    # SPA fallback - uncomment for React/Vue/Angular with client-side routing \
    # location / { \
    #     try_files $uri $uri/ /index.html; \
    # } \
    \
    # Default behavior - serve files as-is \
    location / { \
        try_files $uri $uri/ =404; \
    } \
    \
    # Security headers \
    add_header X-Frame-Options "SAMEORIGIN" always; \
    add_header X-Content-Type-Options "nosniff" always; \
    add_header X-XSS-Protection "1; mode=block" always; \
    add_header Referrer-Policy "strict-origin-when-cross-origin" always; \
    \
    # CORS headers (uncomment if needed for API calls) \
    # add_header Access-Control-Allow-Origin "*" always; \
    # add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always; \
    # add_header Access-Control-Allow-Headers "Origin, Content-Type, Accept, Authorization" always; \
    \
    # Cache static assets \
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ { \
        expires 1y; \
        add_header Cache-Control "public, immutable"; \
    } \
    \
    # No cache for HTML (ensures users get latest version) \
    location ~* \.html?$ { \
        expires -1; \
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"; \
    } \
    \
    # Health check endpoint \
    location /health { \
        access_log off; \
        return 200 "healthy\n"; \
        add_header Content-Type text/plain; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

# Run nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
