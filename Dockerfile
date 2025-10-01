# syntax=docker/dockerfile:1
FROM python:3.13.7-alpine

ARG UID=1000
ARG GID=1000

RUN addgroup -g $GID thirteener
RUN adduser -D -g '' -u $UID -G thirteener thirteener

# Generic labels
LABEL maintainer="Arian Mollik Wasi <arianmollik323@gmail.com>"
LABEL version="0.3.4"
LABEL description="My own custom 12ft.io replacement"
LABEL url="https://github.com/wasi-master/13ft/"
LABEL documentation="https://github.com/wasi-master/13ft/blob/main/README.md"

# OCI compliant labels
LABEL org.opencontainers.image.source="https://github.com/wasi-master/13ft"
LABEL org.opencontainers.image.authors="Arian Mollik Wasi"
LABEL org.opencontainers.image.created="2023-10-31T22:53:00Z"
LABEL org.opencontainers.image.version="0.3.4"
LABEL org.opencontainers.image.url="https://github.com/wasi-master/13ft/"
LABEL org.opencontainers.image.source="https://github.com/wasi-master/13ft/"
LABEL org.opencontainers.image.description="My own custom 12ft.io replacement"
LABEL org.opencontainers.image.documentation="https://github.com/wasi-master/13ft/blob/main/README.md"
LABEL org.opencontainers.image.licenses=MIT

RUN python -m pip install --upgrade pip

USER thirteener
COPY . .
RUN --mount=type=cache,mode=0755,target=/home/thirteener/.cache/pip \
  pip install -U -r requirements.txt

WORKDIR /app
EXPOSE 5000
CMD [ "python", "-m", "gunicorn", "portable:app" ]
