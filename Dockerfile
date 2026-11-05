# syntax=docker/dockerfile:1

FROM node:22.23.4-bookworm-slim AS nodebuild
WORKDIR /app
COPY voyager/env/mineflayer/package.json voyager/env/mineflayer/package-lock.json ./
COPY voyager/env/mineflayer/mineflayer-collectblock ./mineflayer-collectblock
RUN npm ci
RUN npx tsc -p mineflayer-collectblock
RUN npm prune --omit=dev

FROM python:3.11.14-slim-bookworm AS pybuild
WORKDIR /build
RUN apt-get update
RUN apt-get install -y --no-install-recommends build-essential
COPY --from=nodebuild /usr/local/bin/node /usr/local/bin/node
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --prefix=/opt/py -r requirements.txt

FROM python:3.11.14-slim-bookworm
RUN apt-get update
RUN apt-get install -y --no-install-recommends ca-certificates
RUN apt-get install -y --no-install-recommends util-linux
RUN groupadd --gid 10001 voyager
RUN useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin voyager
COPY --from=nodebuild /usr/local/bin/node /usr/local/bin/node
COPY --from=pybuild --chown=voyager:voyager /opt/py /opt/py
ENV PATH=/opt/py/bin:/usr/local/bin:/usr/bin:/bin
ENV PYTHONPATH=/opt/py/lib/python3.11/site-packages:/app
ENV NODE_PATH=/app/voyager/env/mineflayer/node_modules
WORKDIR /app
COPY --chown=voyager:voyager . .
COPY --from=nodebuild --chown=voyager:voyager /app/node_modules /app/voyager/env/mineflayer/node_modules
COPY --from=nodebuild --chown=voyager:voyager /app/mineflayer-collectblock/lib /app/voyager/env/mineflayer/mineflayer-collectblock/lib
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "voyager"]
