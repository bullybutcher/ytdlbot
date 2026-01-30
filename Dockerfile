FROM python:3.12-alpine AS pybuilder
ADD pyproject.toml pdm.lock /build/
WORKDIR /build
RUN apk add alpine-sdk python3-dev musl-dev linux-headers
RUN pip install pdm
RUN pdm install

FROM python:3.12-alpine AS runner
WORKDIR /app

RUN apk update && apk add --no-cache ffmpeg aria2 deno
COPY --from=pybuilder /build/.venv/lib/ /usr/local/lib/
COPY src /app
# Copy mini app and public web UI directories if they exist
COPY mini_app /app/mini_app 2>/dev/null || true
COPY public_web /app/public_web 2>/dev/null || true
WORKDIR /app

CMD ["python" ,"main.py"]
