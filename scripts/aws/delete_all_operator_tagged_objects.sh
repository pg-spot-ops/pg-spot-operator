#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: delete_all_operator_tagged_objects.sh  yes/no (DRY RUN MODE)  ['eu-west-1 eu-north-1' OPTIONAL EXPLICIT REGION LIST]"
  exit 0
fi

echo "Starting at `date`"
set -e

export PAGER=

WET_RUN=0

if [ "${1:0:1}" == "y" ]; then
  WET_RUN=1
fi

if [ -n "$2" ]; then
  REGIONS="$2"
else
  REGIONS=$(aws ec2 describe-regions --no-all-regions --query "Regions[*].[RegionName]" --output text | sort)
fi



if [ "$WET_RUN" -gt 0 ]; then
  echo "WARNING - Deleting all 'pg-spot-operator-instance' tagged resources in regions $REGIONS"
  echo "sleep 5"
  sleep 5
else
  echo "Running in DRY RUN mode - just listing operator resources!"
fi



TOTAL_TERMINATED=0

for reg in $REGIONS ; do

echo ""
echo "*******************"
echo "Processing region: $reg"
echo "*******************"

REGION_TERMINATED=0

echo -e "\n*** Deleting AWS VMs ***"

INSTANCES=$(aws ec2 describe-instances --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance \
  Name=instance-state-name,Values=running,pending,stopped,stopping,shutting-down \
  --query 'Reservations[*].Instances[*].InstanceId' --output text)

for x in $INSTANCES ; do
  echo "Terminating VM $x ..."
  if [ "$WET_RUN" -gt 0 ]; then
    aws ec2 terminate-instances --region $reg --instance-ids $x >/dev/null
    REGION_TERMINATED=$((REGION_TERMINATED+1))
    TOTAL_TERMINATED=$((TOTAL_TERMINATED+1))
  fi
done

echo -e "\nDone. VMs terminated in region: ${REGION_TERMINATED}"


echo -e "\n*** Deleting AWS volumes ***"

REGION_VOLUMES_TERMINATED=0

VOLUMES=$(aws ec2 describe-volumes --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance --query 'Volumes[*].VolumeId' --output text)

if [ "$REGION_TERMINATED" -gt 0 ] && [ -n "$VOLUMES" ] ; then
  echo "Sleeping 5min before deleting volumes to give time to detach ..."
  sleep 300
fi


for vol in $VOLUMES ; do
  echo "Terminating Volume $vol ..."
  if [ "$WET_RUN" -gt 0 ]; then
    vol_state=$(aws ec2 describe-volumes --region $reg --volume-id $vol --query "Volumes[*].State" --output text)
    echo "vol_state: $vol_state"
    if [ "$vol_state" != "available" ]; then
      echo "aws ec2 delete-volume --region $reg --force --volume-id $vol >/dev/null"
      aws ec2 delete-volume --region $reg --force --volume-id $vol >/dev/null
    fi
    echo "aws ec2 delete-volume --region $reg --volume-id $vol >/dev/null"
    aws ec2 delete-volume --region $reg --volume-id $vol >/dev/null
    REGION_VOLUMES_TERMINATED=$((REGION_VOLUMES_TERMINATED+1))
  fi
done

echo -e "\nDone. Volumes terminated: ${REGION_VOLUMES_TERMINATED}"





echo -e "\n*** Deleting AWS Elastic IP Addresses ***"

EIPS_TERMINATED=0

ADDRESSES=$(aws ec2 describe-addresses --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance --query 'Addresses[*].AllocationId' --output text)

for aid in $ADDRESSES ; do
  echo "Terminating address $aid ..."
  if [ "$WET_RUN" -gt 0 ]; then
    aws ec2 release-address --region $reg --allocation-id $aid >/dev/null
    EIPS_TERMINATED=$((EIPS_TERMINATED+1))
  fi
done

echo -e "\nDone. Addresses terminated: ${EIPS_TERMINATED}"




echo -e "\n*** Deleting AWS network interfaces ***"

NICS_TERMINATED=0

NICS=$(aws ec2 describe-network-interfaces --region $reg --filters Name=tag-key,Values=pg-spot-operator-instance \
   Name=interface-type,Values=interface --query 'NetworkInterfaces[*].NetworkInterfaceId' --output text)

for nic in $NICS ; do
  echo "Terminating NIC $nic ..."
  if [ "$WET_RUN" -gt 0 ]; then
    echo "aws ec2 delete-network-interface --region $reg --network-interface-id $nic >/dev/null"
    aws ec2 delete-network-interface --region $reg --network-interface-id $nic >/dev/null
    NICS_TERMINATED=$((NICS_TERMINATED+1))
  fi
done

echo -e "\nDone. NICs terminated: ${NICS_TERMINATED}"





echo -e "\nDone with region ${reg}\n"

done  # reg

echo -e "All regions processed"
echo "Total VMs deleted: $TOTAL_TERMINATED"

echo -e "\nFinished at `date`"
