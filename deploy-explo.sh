#!/bin/bash

echo -e "Deploy an update to Explo Development App Server\n"

export GOOGLE_APPLICATION_CREDENTIALS=./credentials/explo-dev/service-account.json
export PROJECT_ID=explo-dev

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
    # The explo-dev GAE default service is retired and the scheduled jobs run
    # in the DO container, so explo-dev keeps an empty cron configuration
    echo "Cron update for explo-dev is disabled (the jobs run in the DO container)"
}

function default # $1=version
{
    if [[ $1 == "" ]]; then
        echo "Version is missing; enter deploy d[efault] <version>"
        exit 1
    fi
    echo "Default module deployment starting, version '$1'"
    grunt make
    gcloud app deploy --no-cache --version=$1 --no-promote --project=explo-dev app-explo.yaml
    echo "Default module deployment completed"
}

function forward # $1=version
{
    # The forwarding app that stands in for the backend once it has moved
    # to the container deployment (see appspot-forward/main.go). Like
    # 'default', this only uploads the version: it gets no traffic until
    # that is routed to it. The backend's origin (https://host) is taken
    # from the environment, so that it need not be kept in the repository.
    if [[ $1 == "" ]]; then
        echo "Version is missing; enter deploy f[orward] <version>"
        exit 1
    fi
    if [[ ! $FORWARD_TO =~ ^https://[A-Za-z0-9.-]+$ ]]; then
        echo "Set FORWARD_TO to the origin of the backend (https://host)"
        exit 1
    fi
    echo "Forwarding app deployment starting, version '$1'"
    sed "s|REPLACE_ME_backend_origin|$FORWARD_TO|" appspot-forward/app.yaml \
        > appspot-forward/app.deploy.yaml
    gcloud app deploy --version=$1 --no-promote --project=explo-dev appspot-forward/app.deploy.yaml
    result=$?
    rm -f appspot-forward/app.deploy.yaml
    echo "Forwarding app deployment completed"
    return $result
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
    forward|f)
        forward "$version"
        ;;
    *)
        echo "Please enter $0 (stats|indexes|cron|default <version>|forward <version>)"
        exit 1
        ;;
esac
