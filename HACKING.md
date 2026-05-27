# Hacking on the Cockpit Bots

Most bots are python scripts. Shared code is in the tasks/ directory.

## Environment

The bots work in containers that are built in the [cockpituous](https://github.com/cockpit-project/cockpituous)
repository. New dependencies should be added there in the `tasks/container/Containerfile`
file in that repository.

## Bots filing issues and pull requests

Many bots file or work with issues in GitHub repository. Often, certain bots
will file issues or pull requests for tasks that are outstanding.

### Workflows in this repo

These scripts are triggered via GitHub workflows defined in this repo:

- **image-trigger** (`.github/workflows/image-trigger.yml`): Runs on a daily
  schedule (and can be triggered manually).  Checks which images are due for a
  refresh and creates issues with `/image-refresh` commands to kick them off.

- **issue-comment** (`.github/workflows/issue-comment.yml`): Reacts to
  `/image-refresh <image>` comments on issues and PRs.  Submits the image
  build as a job (currently via Testing Farm).

- **naughty-prune** (`.github/workflows/naughty-prune.yml`): Runs weekly to
  clean up the naughty list.

### Scripts used from project repos

These scripts are invoked from GitHub workflows in project repos (e.g. cockpit,
cockpit-podman, etc.):

- **cockpit-lib-update** (`cockpit-lib-update.yml`): Updates
  `COCKPIT_REPO_COMMIT` in Makefiles to track cockpit HEAD and creates a pull
  request.  Not run in the main `cockpit-project/cockpit` repo but used from
  the repos (e.g. cockpit-podman, cockpit-machines, cockpit-files,
  starter-kit) to keep them up to date.

- **po-refresh** (`weblate-sync-po.yml`): Pulls translation updates from
  Fedora Weblate, filters languages below a coverage threshold, and creates a
  pull request.

- **tasks-container-update** (`tasks-container-update.yml`): Fetches the
  latest tag from a container registry and updates the configuration file,
  then creates a pull request.

## Contributing to bots

Development of the bots happens on GitHub at https://github.com/cockpit-project/bots/

There are static code and syntax checks which you should run often:

    test/run

You will need to either use the tasks container to run this script or install:

* python3-mypy
* python3-pytest
* python3-httpx
* python3-respx
* python3-yarl
* ruff

It is highly recommended to set this up as a git pre-push hook, to avoid
pushing PRs that will fail on trivial errors:

    ln -s ../../test/run .git/hooks/pre-push

### Updating pixel tests code

> [!NOTE]
> This will only update the `log.html` page and redirect all links there to the log URL set in `<head>`. For `pixeldiff.html` there is currently no written dev guide.


* Easiest way to develop is to go to `./lib/s3-html/log.html` and within `<head>` add a test URL for what you want to improve layout for.
```html
<base href="https://log-url/log.html" />
<meta http-equiv="refresh" content="5" >
```
* Start a server for the `lib/` directory with `python -m http.server -d ./lib/s3-html`
* Open up the URL echoed in terminal and go to `/log.html`
* Make changes in `log.html` and see changes refresh live in the browser

## Debugging tips

### Boot stock OS images

Our image refreshes find a lot of OS regressions. For reporting these to their respective bug trackers it is useful to reproduce them on stock cloud images. First, locate the current cloud image for e.g. [Fedora rawhide](https://download.fedoraproject.org/pub/fedora/linux/development/rawhide/Cloud/x86_64/images/); look at [images/scripts/*.bootstrap/](images/scripts/) scripts for the other distributions. Download it with

```sh
curl -o os.qcow2 -L IMAGE_URL
```

Then download cockpit CI's cloud config, and boot it in QEMU:

```sh
# nothing fancy, just admin:foobar and root:foobar
curl -L -O https://github.com/cockpit-project/bots/raw/main/machine/cloud-init.iso
qemu-system-x86_64 -cpu host -enable-kvm -nographic -m 2048 -drive file=os.qcow2,if=virtio -snapshot -cdrom cloud-init.iso -net nic,model=virtio -net user,hostfwd=tcp::2201-:22
```

Then log in as user "admin" and password "foobar" on the VT or with ssh
```sh
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o CheckHostIP=no -p 2201 admin@localhost
```
