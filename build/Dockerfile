FROM golang:1.25.14-bookworm
WORKDIR /project
COPY build /project/build
ENV WORKDIR=/tmp/awg-build OUTPUT_DIR=/out
CMD ["bash", "/project/build/build.sh"]
