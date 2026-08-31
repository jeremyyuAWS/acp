# ACP Lite — a single static page served by nginx.
#
# Deliberately NOT built on deploy/public/Dockerfile. That image exists to run the real control
# plane: a FastAPI app, the .NET 10 Office CLI, the Python PDF analyser, LibreOffice, tesseract.
# It takes minutes to build and hundreds of megabytes to ship. ACP Lite is one self-contained
# HTML file with no backend, no database and no engines, so it gets an image that says so — a
# few megabytes, seconds to build, and nothing in it that could be mistaken for the product.
#
# Base via mirror.gcr.io, matching deploy/public/Dockerfile's own note: the Temporal standup hit
# docker.io 429s and every base in this repo has gone through the mirror since.
FROM mirror.gcr.io/library/nginx:1.27-alpine

# Drop nginx's default site rather than layering on top of it — the stock default.conf also
# serves /50x.html from the same root, and leaving it in place means two configs decide what
# happens on an error.
RUN rm -f /etc/nginx/conf.d/default.conf

COPY deploy/lite/nginx.conf /etc/nginx/conf.d/acp-lite.conf
COPY deploy/lite/index.html /usr/share/nginx/html/index.html

# Azure Container Apps routes to the port named in --target-port; 8080 rather than 80 so the
# container needs no root to bind it. nginx:alpine already runs its workers as `nginx`.
EXPOSE 8080

# The stock image's entrypoint handles config templating and signal forwarding; only the
# daemon-off flag is ours, and it is what the base image's own CMD already does. Repeated here
# so a reader does not have to go and check.
CMD ["nginx", "-g", "daemon off;"]
