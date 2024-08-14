FROM python:3.9.18-alpine

# Generic labels
LABEL maintainer="Arian Mollik Wasi <arianmollik323@gmail.com>"
LABEL version="0.3.0"
LABEL description="My own custom 12ft.io replacement"
LABEL url="https://github.com/wasi-master/13ft/"
LABEL documentation="https://github.com/wasi-master/13ft/blob/main/README.md"

# OCI compliant labels
LABEL org.opencontainers.image.source="https://github.com/wasi-master/13ft"
LABEL org.opencontainers.image.authors="Arian Mollik Wasi, Justin Paul, Alfredo Casanova"
LABEL org.opencontainers.image.created="2023-10-31T22:53:00Z"
LABEL org.opencontainers.image.version="0.3.0"
LABEL org.opencontainers.image.url="https://github.com/wasi-master/13ft/"
LABEL org.opencontainers.image.source="https://github.com/wasi-master/13ft/"
LABEL org.opencontainers.image.description="My own custom 12ft.io replacement"
LABEL org.opencontainers.image.documentation="https://github.com/wasi-master/13ft/blob/main/README.md"
LABEL org.opencontainers.image.licenses=MIT

COPY . .
RUN pip install -r requirements.txt
WORKDIR /app
EXPOSE 5000
ENTRYPOINT [ "python" ]
CMD [ "portable.py" ] 