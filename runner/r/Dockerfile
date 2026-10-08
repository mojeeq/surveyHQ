# The sandbox a script runs in.
#
# It holds no secrets, joins no network that reaches anything, and sees one
# job's directory at a time. Everything that makes it safe is in the compose
# service rather than here - this image only has to contain R and the four
# packages a survey script needs.
#
# rocker/r-ver rather than r-base: it points R at Posit's binary repository, so
# arrow installs in a minute instead of compiling for twenty.
FROM rocker/r-ver:4.4.1

# arrow     reads and writes the Parquet the platform speaks
# labelled  carries variable and value labels, which is the part that would
#           otherwise be lost between Stata, the platform and R
# dplyr     the verbs an analyst already thinks in
# jsonlite  the job protocol
RUN install2.r --error --skipinstalled arrow labelled dplyr jsonlite \
    && rm -rf /tmp/downloaded_packages

COPY harness.R /opt/runner/harness.R
COPY entrypoint.sh /opt/runner/entrypoint.sh
RUN chmod +x /opt/runner/entrypoint.sh

# Nothing here runs as root. The compose service drops every capability on top.
USER 65534:65534

ENTRYPOINT ["/opt/runner/entrypoint.sh"]
