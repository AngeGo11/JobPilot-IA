FROM ubuntu:24.04
LABEL authors="axelgomez"

RUN groupadd --system app && useradd --system --gid app --no-create-home app
USER app

ENTRYPOINT ["top", "-b"]
