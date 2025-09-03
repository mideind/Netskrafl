#!/bin/bash

echo -e "Deploy an update to Explo Production App Server\n"

export GOOGLE_APPLICATION_CREDENTIALS="./resources/explo-live-0d431e5fcf4a.json"
export PROJECT_ID=explo-live

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
    gcloud app deploy --no-cache --version=$1 --no-promote --project=explo-live app-explo-live.yaml
    echo "Default module deployment completed"
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
