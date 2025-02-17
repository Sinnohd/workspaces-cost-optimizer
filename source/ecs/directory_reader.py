#!/usr/bin/python 
# -*- coding: utf-8 -*- 
######################################################################################################################
#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.                                           #
#                                                                                                                    #
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance    #
#  with the License. A copy of the License is located at                                                             #
#                                                                                                                    #
#      http://www.apache.org/licenses/LICENSE-2.0                                                                    #
#                                                                                                                    #
#  or in the "license" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES #
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions    #
#  and limitations under the License.                                                                                #
######################################################################################################################

# This file calls the workspaces_helper module to read cloudwatch logs.  The only AWS activity in this file
# is writing the CSV file to S3 and making a call to our tracking url.

import boto3
import botocore
from botocore.exceptions import ClientError
import logging
import time
from botocore.config import Config
from ecs.workspaces_helper import WorkspacesHelper
import os

log = logging.getLogger()
LOG_LEVEL = str(os.getenv('LogLevel', 'INFO'))
log.setLevel(LOG_LEVEL)

class DirectoryReader(object):

    def __init__(self):
        return

    def read_directory(self, region, stackParams, directoryParams):
        botoConfig = Config(
            max_pool_connections=100,
            user_agent_extra=os.getenv('UserAgentString'),
            retries={
                'max_attempts': 20,
                'mode': 'standard'
            }
        )
        maxRetries = 3
        workspaceCount = 0
        testEndOfMonth = False
        sendAnonymousData = False
        isDryRun = True

        endTime = directoryParams['EndTime']
        startTime = directoryParams['StartTime']
        lastDay = directoryParams['LastDay']
        runUUID = directoryParams['RunUUID']

        list_processed_workspaces = []
        # Provide point to clean up parameter names in the future.
        if stackParams['DryRun'] == 'No':
            isDryRun = False

        # CloudFormation overrides the end-of-month testing
        if stackParams['TestEndOfMonth'] == 'Yes':
            testEndOfMonth = True
            log.info('Setting testEndOfMonth to %s', testEndOfMonth)

        # Should we send Solutiuon Team metrics
        if stackParams['SendAnonymousData'] == 'true':
            sendAnonymousData = True
            log.debug('sendAnonymousData: %s', sendAnonymousData)

        awsS3Bucket = stackParams['BucketName']
        log.info('Output Bucket: %s', awsS3Bucket)

        # Capture the directoryId passed to the function
        if 'DirectoryId' in directoryParams:
            directoryID = directoryParams['DirectoryId']
        else:
            log.error('Failed to find directoryId in directoryParams')
            return 0

        try:
            directoryParams['CSV']
        except:
            wsCsv = 'WorkspaceID,Billable Hours,Usage Threshold,Change Reported,Bundle Type,Initial Mode,New Mode,Username,Computername,DirectoryId,Tags\n'
        else:
            wsCsv = directoryParams['CSV']

        try:
            directoryParams['NextToken']
        except:
            nextToken = 'None'
        else:
            nextToken = directoryParams['NextToken']

        # List of bundles with specific hourly limits
        workspacesHelper = WorkspacesHelper({
            'region': region,
            'hourlyLimits': {
                'VALUE': stackParams['ValueLimit'],
                'STANDARD': stackParams['StandardLimit'],
                'PERFORMANCE': stackParams['PerformanceLimit'],
                'POWER': stackParams['PowerLimit'],
                'POWERPRO': stackParams['PowerProLimit'],
                'GRAPHICS': stackParams['GraphicsLimit'],
                'GRAPHICSPRO': stackParams['GraphicsProLimit']
            },
            'testEndOfMonth': testEndOfMonth,
            'isDryRun': isDryRun,
            'startTime': startTime,
            'endTime': endTime
        })

        morePages = True
        while morePages:  # looping through all pages of the directory, 25 at a time
            workspacesPage = workspacesHelper.get_workspaces_page(directoryID, nextToken)

            try:
                workspacesPage['NextToken']
            except:
                nextToken = 'None'
            else:
                nextToken = workspacesPage['NextToken']

            # Loop through list of workspaces in current page of directory
            for workspace in workspacesPage['Workspaces']:
                log.info("Workspace Object")
                log.info(workspace)
                result = workspacesHelper.process_workspace(workspace)
                workspaceCount = workspaceCount + 1
                log.info('Workspace %d -> %s', workspaceCount, result)
                log.info('Appending CSV file')
                # Append result data to the CSV
                wsCsv = workspacesHelper.append_entry(wsCsv, result)
                try:
                    workspace_processed = {
                        'previousMode': result['initialMode'],
                        'newMode': result['newMode'],
                        'bundleType': result['bundleType'],
                        'hourlyThreshold': result['hourlyThreshold'],
                        'billableTime': result['billableTime']
                    }
                    list_processed_workspaces.append(workspace_processed)
                except Exception as e:
                    pass
            if nextToken == 'None':
                morePages = False
                log.info('Last page, finished %d workspaces, putting csv file in S3', workspaceCount)
                pEndTime = time.strptime(endTime, '%Y-%m-%dT%H:%M:%SZ')
                s3Client = boto3.client('s3', config=botoConfig)

                logBody = workspacesHelper.expand_csv(wsCsv)
                logKey = time.strftime('%Y/%m/%d/', pEndTime) + region + '_' + directoryID

                if testEndOfMonth:
                    logKey += '_end-of-month'
                else:
                    logKey += '_daily'

                if isDryRun:
                    logKey += '_dry-run'

                logKey += '.csv'

                log.debug('Uploading workspace report to S3 for region {}'.format(region))
                try:
                    s3Client.put_object(
                        Bucket=awsS3Bucket,
                        Body=logBody,
                        Key=logKey
                    )
                    log.info('Successfully uploaded csv file to %s', logKey)
                    break
                except botocore.exceptions.ClientError as e:
                    log.error(e)
            else:
                # Loop back to the top of while loop and process another page of workspaces for this directory (every 25 workspaces)
                log.info('Calling read_directory again for next page with nextToken -> %s', nextToken)
        return workspaceCount, list_processed_workspaces
