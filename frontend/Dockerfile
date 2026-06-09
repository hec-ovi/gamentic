FROM nginx:1.27-alpine

# Reverse-proxy config (serves the static app + proxies /image, /voice, /audio same-origin)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static app
COPY . /usr/share/nginx/html

EXPOSE 80
