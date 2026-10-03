FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# A template rather than a finished config: the Content-Security-Policy has to
# name the origin module assets are actually delivered from, which differs
# between a local LocalStack and a deployed bucket. nginx's own entrypoint runs
# envsubst over /etc/nginx/templates at start-up; NGINX_ENVSUBST_FILTER keeps it
# to the one variable, so nothing substitutes nginx's own $host or $uri.
ENV NGINX_ENVSUBST_FILTER=ASSET_ORIGIN
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
