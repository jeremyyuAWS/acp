FROM grafana/grafana:11.6.0

# Bake provisioning config and dashboards into the image.
#
# THE COMMENT THAT USED TO BE HERE WAS WRONG ABOUT ITS OWN IMAGE. It said the connection arrives
# "via GF_DATASOURCES_DEFAULT_URL (or the full DSN via DATABASE_URL env var — see datasource.yaml)"
# and pointed at the file that contradicts it: provisioning/datasources/acp-postgres.yaml reads
# ACP_GRAFANA_PG_HOST, _DB, _USER and _PASS, and nothing in this image has ever read either name
# the comment gave. Anyone wiring a new deployment path from that sentence would have set two
# variables Grafana ignores and got a datasource with four empty fields — which Grafana provisions
# happily and which fails later, as dashboards that render no data.
#
# It is true NOW, because acp-entrypoint.sh makes it true: DATABASE_URL is accepted and split into
# the four the file needs, for callers that have a DSN and not the parts. Fixed rather than
# deleted, because the sentence described the interface somebody wanted; it just did not exist.
COPY provisioning/ /etc/grafana/provisioning/
COPY dashboards/   /var/lib/grafana/dashboards/
COPY acp-entrypoint.sh /acp-entrypoint.sh

USER root
RUN chmod +x /acp-entrypoint.sh
USER 472

# The base image's own entrypoint is /run.sh (read from the registry config of
# grafana/grafana:11.6.0, not assumed); acp-entrypoint.sh execs it after deriving the datasource
# variables, so everything downstream of this line behaves exactly as the stock image does.
ENTRYPOINT ["/acp-entrypoint.sh"]

ENV GF_SERVER_ROOT_URL=""
ENV GF_AUTH_ANONYMOUS_ENABLED=true
ENV GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
ENV GF_AUTH_DISABLE_LOGIN_FORM=false
ENV GF_SECURITY_ALLOW_EMBEDDING=true
ENV GF_USERS_DEFAULT_THEME=light
ENV GF_ANALYTICS_REPORTING_ENABLED=false
ENV GF_ANALYTICS_CHECK_FOR_UPDATES=false
