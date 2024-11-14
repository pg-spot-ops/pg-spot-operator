#!/bin/bash

if [ ! -f /app/.ssh/id_rsa ]; then

  # Generate a default ssh key, but mostly probably want to bind specify an AWS key-pair or extra user keys also
  ssh-keygen -q -f /app/.ssh/id_rsa -t ed25519 -N ''

fi

exec python -m pg_spot_operator
