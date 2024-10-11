FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && pip install ansible

RUN apt-get -q update && DEBIAN_FRONTEND=noninteractive apt-get install -qy curl unzip apt-transport-https \
    ca-certificates gnupg lsb-release less vim openssh-client jq \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Generate a default ssh key, but mostly probably want to bind local .ssh
RUN mkdir /root/.ssh  ; if [ ! -f /root/.ssh/id_rsa ] ; then ssh-keygen -q -f /root/.ssh/id_rsa -t ed25519 -N '' ; fi

ADD pg_spot_operator pg_spot_operator

ADD ansible ansible

ADD tuning_profiles tuning_profiles

CMD ["python", "-m", "pg_spot_operator"]
