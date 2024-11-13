FROM python:3.12-slim

ENV HOME=/app

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && pip install ansible

RUN apt-get -q update && DEBIAN_FRONTEND=noninteractive apt-get install -qy curl unzip apt-transport-https \
    ca-certificates gnupg lsb-release less vim openssh-client jq \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN chown -R nobody /app

USER nobody

# Generate a default ssh key, but mostly probably want to bind local .ssh
RUN mkdir /app/.ssh  ; if [ ! -f /app/.ssh/id_rsa ] ; then ssh-keygen -q -f /app/.ssh/id_rsa -t ed25519 -N '' ; fi

ADD pg_spot_operator pg_spot_operator

ADD ansible ansible

ADD tuning_profiles tuning_profiles

CMD ["python", "-m", "pg_spot_operator"]
