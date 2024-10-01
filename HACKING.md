# Hacking on the Cockpit Bots

Most bots are python scripts. Shared code is in the tasks/ directory.

## Environment

The bots work in containers that are built in the [cockpituous](https://github.com/cockpit-project/cockpituous)
repository. New dependencies should be added there in the `tasks/container/Containerfile`
file in that repository.

## Bots filing issues

Many bots file or work with issues in GitHub repository. We can use issues to tell
bots what to do. Often certan bots will just file issues for tasks that are outstanding.
And in many cases other bots will then perform those tasks.

These bots are listed in the `./issue-scan` file. They are written using the
`tasks/__init__.py` code. These are deprecated in favor of GitHub workflows.

## Bots printing output

The bots which run on our own infrastructure post their output into the
requesting GitHub issue. This currently only applies to `image-refresh`, all
other bots run in GitHub actions.

## Contributing to bots

Development of the bots happens on GitHub at https://github.com/cockpit-project/bots/

There are static code and syntax checks which you should run often:

    test/run

You will need to either use the tasks container to run this script or install:

* python3-mypy
* python3-pytest
* python3-aioresponses
* python3-aiohttp
* ruff

It is highly recommended to set this up as a git pre-push hook, to avoid
pushing PRs that will fail on trivial errors:

    ln -s ../../test/run .git/hooks/pre-push
