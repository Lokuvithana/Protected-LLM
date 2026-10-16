FROM nginx:1.27-alpine
# *.template files are filled with environment variables (SERVICE_KEY) at start-up.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/
EXPOSE 80
