FROM grafana/grafana:11.6.0

# Bake provisioning config and dashboards into the image.
# The Postgres connection URL is injected at runtime via GF_DATASOURCES_DEFAULT_URL
# (or the full DSN via DATABASE_URL env var — see datasource.yaml).
COPY provisioning/ /etc/grafana/provisioning/
COPY dashboards/   /var/lib/grafana/dashboards/

ENV GF_SERVER_ROOT_URL=""
ENV GF_AUTH_ANONYMOUS_ENABLED=true
ENV GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
ENV GF_AUTH_DISABLE_LOGIN_FORM=false
ENV GF_SECURITY_ALLOW_EMBEDDING=true
ENV GF_USERS_DEFAULT_THEME=light
ENV GF_ANALYTICS_REPORTING_ENABLED=false
ENV GF_ANALYTICS_CHECK_FOR_UPDATES=false
