FROM nginx:alpine

RUN apk add --no-cache openssl


# We expect certs to be mounted at /etc/nginx/certs
# No self-signed generation here to support mkcert

COPY conf.d/default.conf /etc/nginx/conf.d/default.conf
