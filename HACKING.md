# Hacking on the Cockpit Bots

Most bots are python scripts. Shared code is in the tasks/ directory.

## Environment

The bots work in containers that are built in the [cockpituous](https://github.com/cockpit-project/cockpituous)
repository. New dependencies should be added there in the `tasks/Dockerfile`
file in that repository.

## Bots filing issues

Many bots file or work with issues in GitHub repository. We can use issues to tell
bots what to do. Often certan bots will just file issues for tasks that are outstanding.
And in many cases other bots will then perform those tasks.

These bots are listed in the `./issue-scan` file. They are written using the
`tasks/__init__.py` code. These are deprecated in favor of GitHub workflows.

## Bots printing output

The bot output is posted using the cockpitous [sink](https://github.com/cockpit-project/cockpituous/tree/main/sink) code. See that link for how it works.

## Contributing to bots

Development of the bots happens on GitHub at https://github.com/cockpit-project/bots/

There are static code and syntax checks which you should run often:

    $ test/run

You will need to install the python3-flake8 package for python3 in order to run
this script.

It is highly recommended to set this up as a git pre-push hook, to avoid
pushing PRs that will fail on trivial errors:

    $ ln -s ../../test/run .git/hooks/pre-push
