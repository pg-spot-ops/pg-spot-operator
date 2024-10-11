#!/bin/bash

echo "Starting at `date`"
set -e

export PAGER=

REGIONS=$(aws ec2 describe-regions --no-all-regions --query "Regions[*].[RegionName]" --output text)
WET_RUN=

if [ -n "$1" ]; then
  WET_RUN=t
fi

if [ -z "$WET_RUN" ]; then
  echo "Running in DRY RUN mode ! Add any argument to actually delete"
else
  echo "WARNING - Deleting all 'pg-spot-operator-instance' tagged resources in regions $REGIONS"
  echo "sleep 5"
  sleep 5
fi



### VMs ###

echo -e "\n*** Deleting AWS VMs ***"

TERMINATED=0

for reg in $REGIONS ; do
echo -e "\nProcessing region: $reg\n"

INSTANCES=$(aws ec2 describe-instances --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance \
  Name=instance-state-name,Values=running,pending,stopped,stopping,shutting-down \
  --query 'Reservations[*].Instances[*].InstanceId' --output text)

for x in $INSTANCES ; do
  echo "Terminating VM $x ..."
  if [ -n "$WET_RUN" ]; then
    aws ec2 terminate-instances --region $reg --instance-ids $x >/dev/null
    TERMINATED=$((TERMINATED+1))
  fi
done

done  # reg
echo -e "\nDone. VMs terminated: ${TERMINATED}"

if [ "$TERMINATED" -gt 0 ]; then
  echo "Sleeping 5min before deleting volumes to give time to detach ..."
  sleep 300
fi


### VOLUMES ###

echo -e "\n*** Deleting AWS volumes ***"

TERMINATED=0

for reg in $REGIONS ; do
echo -e "\nProcessing region: $reg\n"

VOLUMES=$(aws ec2 describe-volumes --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance --query 'Volumes[*].VolumeId' --output text)

for vol in $VOLUMES ; do
  echo "Terminating Volume $vol ..."
  if [ -n "$WET_RUN" ]; then
    vol_state=$(aws ec2 describe-volumes --region $reg --volume-id $vol --query "Volumes[*].State" --output text)
    echo "vol_state: $vol_state"
    if [ "$vol_state" != "available" ]; then
      echo "aws ec2 delete-volume --region $reg --force --volume-id $vol >/dev/null"
      aws ec2 delete-volume --region $reg --force --volume-id $vol >/dev/null
    fi
    echo "aws ec2 delete-volume --region $reg --volume-id $vol >/dev/null"
    aws ec2 delete-volume --region $reg --volume-id $vol >/dev/null
    TERMINATED=$((TERMINATED+1))
  fi
done

done
echo -e "\nDone. Volumes terminated: ${TERMINATED}"


### Elastic Public IPs

echo -e "\n*** Deleting AWS Elastic IP Addresses ***"

TERMINATED=0

for reg in $REGIONS ; do
echo -e "\nProcessing region: $reg\n"

ADDRESSES=$(aws ec2 describe-addresses --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance --query 'Addresses[*].AllocationId' --output text)

for aid in $ADDRESSES ; do
  echo "Terminating address $aid ..."
  if [ -n "$WET_RUN" ]; then
    aws ec2 release-address --region $reg --allocation-id $aid >/dev/null
    TERMINATED=$((TERMINATED+1))
  fi
done

done
echo -e "\nDone. Addresses terminated: ${TERMINATED}"



### NICs

echo -e "\n*** Deleting AWS network interfaces ***"

TERMINATED=0

for reg in $REGIONS ; do
echo -e "\nProcessing region: $reg\n"

NICS=$(aws ec2 describe-network-interfaces --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance \
   Name=interface-type,Values=interface --query 'NetworkInterfaces[*].NetworkInterfaceId' --output text)

for nic in $NICS ; do
  echo "Terminating NIC $nic ..."
  if [ -n "$WET_RUN" ]; then
    echo "aws ec2 delete-network-interface --region $reg --network-interface-id $nic >/dev/null"
    aws ec2 delete-network-interface --region $reg --network-interface-id $nic >/dev/null
    TERMINATED=$((TERMINATED+1))
  fi
done

done
echo -e "Done. NICs terminated: ${TERMINATED}"

echo "Finished at `date`"
