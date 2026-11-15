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
    # Netskrafl's backend runs in the container deployment since 2026-11-13,
    # and so do its scheduled jobs: App Engine keeps an empty cron configuration
    echo "Cron update for netskrafl is disabled (the jobs run in the container)"
}

function redirect # $1=version
{
    # The redirect app that stands in for the retired backend on App Engine
    # (see appspot-redirect/main.py). Like 'default', this only uploads the
    # version: it gets no traffic until that is routed to it.
    if [[ $1 == "" ]]; then
        echo "Version is missing; enter deploy r[edirect] <version>"
        exit 1
    fi
    echo "Redirect app deployment starting, version '$1'"
    gcloud app deploy --version=$1 --no-promote --project=netskrafl appspot-redirect/app.yaml
    echo "Redirect app deployment completed"
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
    redirect|r)
        redirect "$version"
        ;;
    *)
        echo "Please enter $0 (stats|indexes|cron|default <version>|redirect <version>)"
        exit 1
        ;;
esac
