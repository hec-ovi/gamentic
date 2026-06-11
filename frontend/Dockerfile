FROM nginx:1.27-alpine

# Reverse-proxy config (serves the static app + proxies /image, /voice, /audio
# same-origin). It is an envsubst TEMPLATE: the entrypoint substitutes only the
# variables defined below (nginx's own $vars are untouched), so the /voice
# target can be retargeted at the orchestrator for cloud audio without a
# rebuild: -e VOICE_UPSTREAM=http://gamentic-orchestrator:8000 -e VOICE_PATH_PREFIX=/audio
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV VOICE_UPSTREAM=http://gamentic-voice-api:8080 \
    VOICE_PATH_PREFIX=/voice

# Static app
COPY . /usr/share/nginx/html

EXPOSE 80
