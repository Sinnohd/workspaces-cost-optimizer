#!/bin/bash

# Build Lambda zip
echo "------------------------------------------------------------------------------"
echo "[Packing] lambda code"
echo "------------------------------------------------------------------------------"

cd $1
# install third party library for python 3.8, 3.7 used botocore.vendor.requests
pip3 install requests -t . --system
ls -alt
zip -q -r9 $2/workspaces-cost-optimizer.zip .
zip -q -d  $2/workspaces-cost-optimizer.zip *fargate-schedule.py
echo "Completed building distribution"

