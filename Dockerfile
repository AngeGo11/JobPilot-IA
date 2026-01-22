FROM ubuntu:latest
LABEL authors="axelgomez"

ENTRYPOINT ["top", "-b"]