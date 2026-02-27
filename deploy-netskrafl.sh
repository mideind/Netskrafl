#!/bin/bash

echo -e "Deploy an update to Netskrafl App Server\n"

export GOOGLE_APPLICATION_CREDENTIALS=./credentials/netskrafl/service-account.json
export PROJECT_ID=netskrafl

cmd=$1
version=$2

function stats
{
    echo "Skraflstats deployment starting"
    echo "*** Currently disabled ***"
    echo "Skraflstats deployment completed"
}

function indexes
{
    echo "Index update starting"
    echo "*** Currently disabled ***"
    echo "Index update completed"
}

function cron
{
    echo "Cron update starting"
    echo "*** Currently disabled ***"
    echo "Cron update completed"
}

function default # $1=version
{
    if [[ $1 == "" ]]; then
        echo "Version is missing; enter deploy d[efault] <version>"
        exit 1
    fi
    echo "Default module deployment starting, version '$1'"
    grunt make
    gcloud app deploy --no-cache --version=$1 --no-promote --project=netskrafl app-netskrafl.yaml
    echo "Default module deployment completed"

    # Prompt to update Cloud Scheduler job
    read -p "Update Cloud Scheduler job 'update_online_status' to use version '$1'? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Updating Cloud Scheduler job..."
        gcloud scheduler jobs update app-engine update_online_status \
            --version=$1 \
            --project=netskrafl
        echo "Cloud Scheduler job updated successfully"
    else
        echo "Skipped Cloud Scheduler update. REMEMBER to update manually if needed."
    fi
}

case $cmd in
    skraflstats|stats|s)
        stats
        ;;
    indexes|ix|i)
        indexes
        ;;
    cron|c)
        cron
        ;;
    default|d)
        default "$version"
        ;;
    *)
        echo "Please enter $0 (stats|indexes|cron|default <version>)"
        exit 1
        ;;
esac
