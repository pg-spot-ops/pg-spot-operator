FROM python:3.12-slim

ENV HOME=/app

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && pip install ansible

RUN apt-get -q update && DEBIAN_FRONTEND=noninteractive apt-get install -qy curl unzip apt-transport-https \
    ca-certificates gnupg lsb-release less vim openssh-client jq dumb-init \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -s /app /nonexistent && chown -R nobody /app

COPY entrypoint.sh .

USER nobody

ADD pg_spot_operator pg_spot_operator

ADD ansible ansible

ADD tuning_profiles tuning_profiles

ENTRYPOINT ["dumb-init", "/app/entrypoint.sh"]
