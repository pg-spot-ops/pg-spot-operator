#!/bin/bash

# Create an instance with all Postgres features enabled and try to connect to it via psql

if ! command -v pipx >/dev/null ; then
  echo "pipx not found"
  exit 1
fi

if ! command -v yq >/dev/null ; then
  echo "yq not found"
  exit 1
fi

set -u -o pipefail

ST_CONFIG_DIR=~/.pg-spot-operator-smoke-test
ST_PIPX_DIR=$ST_CONFIG_DIR/pipx
LOGDIR=$ST_CONFIG_DIR/logs
USE_LATEST_PRIVATE_PIPX=f  # 'y' to update
CHECK_PRICE_ONLY=
LOOP_SLEEP=60
MAX_RUNTIME_SECONDS=604800  # 1w
NOTIFY_URL_FILE_FAILURE=~/.pg-spot-operator-smoke-test-notify-url-failure  # If found a curl request is sent when Postgres goes down
NOTIFY_URL_FILE_SUCCESS=~/.pg-spot-operator-smoke-test-notify-url-success  # If found a curl request is sent if Postgres comes up

# Operator params
REGION=eu-north-1
INSTANCE_MANIFEST_PATH=smoke1_network_storage.yaml
INSTANCE_NAME=$(cat $INSTANCE_MANIFEST_PATH | yq -r .instance_name)

if [ -z "$INSTANCE_NAME" ]; then
  echo "Could not parse instance_name, check manifest at $INSTANCE_MANIFEST_PATH"
  exit 1
fi

function notify_url() {
  # 0 = OK, 1 = ERR
  NOTIFY_URL_FILE=$NOTIFY_URL_FILE_FAILURE
  if [ "$1" -eq 0 ]; then
    NOTIFY_URL_FILE=$NOTIFY_URL_FILE_SUCCESS
  fi

  if [ ! -f $NOTIFY_URL_FILE ]; then
    echo "Warning: NOTIFY_URL_FILE at $NOTIFY_URL_FILE not found"
    return 1
  fi

  NOTIFY_URL=$(cat $NOTIFY_URL_FILE)
  if [ -z "$NOTIFY_URL" ]; then
    echo "Warning: empty NOTIFY_URL"
    return 1
  fi
  echo "Sending a notify to $NOTIFY_URL"
  if curl -skL --retry 5 "$NOTIFY_URL" ; then
    echo "Notify OK"
    return 0
  else
    echo "ERROR failed to notify"
    return 1
  fi
}

echo "Starting at $(date --rfc-3339=s) ..."
echo "ST_CONFIG_DIR=$ST_CONFIG_DIR"

mkdir "$ST_CONFIG_DIR" "$LOGDIR" 2>/dev/null

if [ "$USE_LATEST_PRIVATE_PIPX" == "y" ] ; then
  mkdir $ST_PIPX_DIR $ST_PIPX_DIR/pipx 2>/dev/null
  PIPX_HOME=${ST_PIPX_DIR} PIPX_BIN_DIR=${ST_PIPX_DIR}/bin pipx install --force pg-spot-operator
  PATH=${ST_PIPX_DIR}/bin:/usr/local/bin:/usr/bin
fi

echo "Using pg_spot_operator from: `which pg_spot_operator`"

pg_spot_operator --check-price --region $REGION &>> $LOGDIR/check_price_${INSTANCE_NAME}_`date --rfc-3339=d`.log

if [ -n "$CHECK_PRICE_ONLY" ]; then
  echo "Exiting due to $CHECK_PRICE_ONLY"
  exit 0
fi


FAILING=0


# Main loop
while true ; do

  while true ; do

    echo "Loop start at $(date --rfc-3339=s) ..."

    # Create the instance and store the connect string
    echo "Provisioning ..."
    CONNSTR=$(pg_spot_operator --manifest-path $INSTANCE_MANIFEST_PATH --connstr-only --verbose 2>>$LOGDIR/provision_${INSTANCE_NAME}_`date --rfc-3339=d`.log)
    echo "OK. CONNSTR=$CONNSTR"

    # Test Postgres connectivity
    ROWCOUNT=$(psql $CONNSTR -XAtc "select count(*) from pg_stat_user_tables where relname = 'pgbench_accounts'")
    if [ "$?" -ne 0 ]; then
      FAILING=1
      notify_url $FAILING
      break
    fi

    if [ "$ROWCOUNT" == '0' ]; then
      echo "Init pgbench schema ..."
      pgbench -iq "$CONNSTR" >/dev/null
      if [ "$?" -ne 0 ]; then
        FAILING=1
        notify_url $FAILING
        break
      fi
    fi

    echo "Doing 1 pgbench TX ..."
    pgbench -n -t 1 "$CONNSTR" >/dev/null
    if [ "$?" -ne 0 ]; then
      echo "pgbench TX fail"
      FAILING=1
      notify_url $FAILING
      break
    fi

    echo "pgbench TX OK"
    FAILING=0
    notify_url $FAILING
    break

  done

  echo "Loop done"
  echo "Sleeping $LOOP_SLEEP s at $(date --rfc-3339=s) ..."
  sleep $LOOP_SLEEP

done

echo "Script finished at $(date --rfc-3339=s)"
