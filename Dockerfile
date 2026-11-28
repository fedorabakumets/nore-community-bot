FROM denoland/deno:bin-2.6.10 AS deno
FROM node:24-bookworm-slim AS poker
WORKDIR /poker
COPY poker/package*.json ./
RUN npm ci
COPY poker/build.mjs poker/LICENSE ./
COPY poker/src ./src
COPY poker/art ./art
RUN npm run build

FROM python:3.12-slim AS whisper

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates cmake curl g++ make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
# whisper.cpp v1.8.4 and its multilingual tiny model, pinned and verified at build time.
RUN curl -fsSL --retry 3 https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/9386f239401074690479731c1e41683fbbeac557 -o source.tar.gz \
    && echo '0cc49e22729edd3cd2e7727522b456f459e1860fe65e975b39ce1a194857f9d5  source.tar.gz' | sha256sum -c - \
    && tar -xzf source.tar.gz --strip-components=1 \
    && cmake -S . -B out -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
       -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
    && cmake --build out --target whisper-cli --parallel 2 \
    && mkdir -p /opt/nora/whisper \
    && cp out/bin/whisper-cli LICENSE /opt/nora/whisper/ \
    && cd /opt/nora/whisper \
    && curl -fsSL --retry 3 https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny-q5_1.bin -o ggml-tiny-q5_1.bin \
    && echo '818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7  ggml-tiny-q5_1.bin' | sha256sum -c -

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=deno /deno /usr/bin/deno
COPY --from=poker /poker/dist /app/poker/dist
COPY --from=whisper /opt/nora/whisper /opt/nora/whisper
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY community_bot ./community_bot
COPY assets ./assets
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN pip install . \
    && python -m community_bot.menu_art \
    && useradd --create-home --uid 10001 botuser \
    && mkdir -p /app/data \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R botuser:botuser /app

# Stay root so a Railway volume mounted at /app/data is writable, then drop privileges.
USER root
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "community_bot.main"]
