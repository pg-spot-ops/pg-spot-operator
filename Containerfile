FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

ENV HOME=/app

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && pip install ansible

RUN apt-get -q update && DEBIAN_FRONTEND=noninteractive apt-get install -qy curl unzip apt-transport-https \
    ca-certificates gnupg lsb-release less openssh-client dumb-init \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh .

# Create a non-privileged user and group
RUN useradd -u 5432 -g root -d /app -m -s /bin/bash app && mkdir /app/.ssh && chown -R app /app

USER 5432

ADD pg_spot_operator pg_spot_operator

ADD ansible ansible

ADD tuning_profiles tuning_profiles

ENTRYPOINT ["dumb-init", "/app/entrypoint.sh"]
