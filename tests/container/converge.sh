#!/usr/bin/env bash
# Apply the roles that need no kernel module, no EFS and no AWS to a container,
# the way a head node applies them to itself at first boot, and then apply them
# again to prove that a second run changes nothing.
#
#   tests/container/converge.sh            run, and remove the container
#   KEEP=1 tests/container/converge.sh     leave the container for a look
#   PLAYS="site users" ROLES=sandbox_paths tests/container/converge.sh
#                                          a part: some plays, some roles of site.yml
#
# The plays are site.yml (with the roles below), users.yml (with the users of
# tests/container/users.yml) and jupyterhub.yml, in that order.
#
# After the second apply, the roles that reach Spack through the csis_spack
# collection are run once more in check mode, which must find nothing to change.
#
# spack_environment is applied with spack_environment_state: concretized
# (tests/container/vars.yml): ESMF and PETSc are concretized with the real
# oneAPI and Spack, and not built. Fake installs cannot stand in for the build:
# they leave python-venv without the python3 that the rest of the tree needs.
#
# Not exercised here: efa_driver, fsx_lustre_client, hpc_tuning and
# node-image.yml. See docs/LIVE-PROOF.md.

set -euo pipefail

unit=$(cd "$(dirname "$0")/../.." && pwd)
image=sandbox-provisioning-test:alma10
container=sandbox-provisioning-test-$$
logs=$(mktemp -d)
roles=${ROLES:-sandbox_paths,user_shell,base_system,prefect_server,mpi_ssh,python_user_env,spack,intel_oneapi,spack_environment}
plays=${PLAYS:-site users jupyterhub}

cleanup() {
    if [ "${KEEP:-0}" = 1 ]; then
        echo "container kept: $container; logs in $logs"
    else
        docker rm --force "$container" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# A process started in this container gets a umask of 0000. Files made with it
# are writable by anyone, and Ansible ignores an ansible.cfg in a directory
# like that. Cloud-init runs with 022, so that is what is used here.
in_container() { docker exec "$container" bash -c 'umask 022; exec "$@"' -- "$@"; }

echo "== building the image"
docker build --quiet --tag "$image" "$unit/tests/container" >/dev/null

echo "== starting the container"
docker run --detach --name "$container" --privileged --cgroupns=host \
    --volume /sys/fs/cgroup:/sys/fs/cgroup:rw "$image" >/dev/null
for _ in $(seq 1 60); do
    state=$(in_container systemctl is-system-running 2>/dev/null || true)
    case "$state" in running | degraded) break ;; esac
    sleep 1
done
echo "   systemd is $state"

echo "== what the first-boot template does before the playbook: the shared directories"
in_container bash -c '
    set -e
    mkdir -p /mnt/efs/fs1/save
    chgrp wheel /mnt/efs/fs1/save
    chmod 777 /mnt/efs/fs1/save
    ln -s /mnt/efs/fs1/save /save
    mkdir /mnt/efs/fs1/save/ec2-user
    chown ec2-user:ec2-user /mnt/efs/fs1/save/ec2-user
'

case " $plays " in
    *" site "*)
        case ",$roles," in
            *",spack,"*)
                echo "== the login user's Spack scope, as a head node built before stage 11 has it"
                # The script's "config add" without --scope left the padding and
                # the Tcl modules here. The padding is as the script left it,
                # and goes; the modules setting is changed, as if by hand, and
                # stays (stage 12).
                in_container sudo -u ec2-user bash -c '
                    set -e
                    mkdir -p ~/.spack
                    printf "config:\n  install_tree:\n    padded_length: 73\n" > ~/.spack/config.yaml
                    printf "modules:\n  default:\n    enable:\n    - lmod\n" > ~/.spack/modules.yaml
                '
                ;;
        esac
        ;;
esac

echo "== putting the playbooks in a git repository inside the container"
in_container mkdir -p /srv/provisioning
# ustar: no extended attributes from the host. Extracted as root's own files,
# or git refuses to work in a directory that someone else owns.
# The unit's own .git stays behind: what is tested is the files as they are
# now, committed or not, in a repository made for the test. With it, the commit
# below finds nothing to commit (a repository of its own) or a pointer to a
# directory that is not in the container (a submodule).
tar -C "$unit" --format ustar --exclude=./.git --exclude=.venv --exclude=.collections \
    --exclude=.pytest_cache --exclude=.ruff_cache --exclude=__pycache__ -cf - . |
    docker exec --interactive "$container" tar -C /srv/provisioning --no-same-owner -xf -
in_container bash -c '
    set -e
    cd /srv/provisioning
    git init --quiet --initial-branch main
    git add --all
    git -c user.name=test -c user.email=test@example.invalid commit --quiet --message "under test"
'

echo "== fetching the playbooks and installing their collections, as the first-boot template does"
# ansible-pull installs no collections, and site.yml needs one: the checkout
# comes first, then requirements.yml, then the plays.
if ! in_container bash -c '
    set -e
    git clone --quiet --branch main /srv/provisioning /opt/sandbox-provisioning
    cd /opt/sandbox-provisioning
    ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg ansible-galaxy collection install -r requirements.yml
' >"$logs/collections.log" 2>&1; then
    tail -30 "$logs/collections.log"
    echo "FAILED: the collections did not install; full log in $logs/collections.log"
    exit 1
fi
grep -E 'was installed successfully' "$logs/collections.log" | sed 's/^/   /'

# ansible-pull hands the extra variables to its checkout step too, so the files
# have to exist before the checkout does: they are read from the source repository.
apply_play() {
    local play=$1
    local -a extra=(--extra-vars @/srv/provisioning/tests/container/vars.yml)
    case "$play" in
        site) extra+=(--tags "$roles") ;;
        users) extra+=(--extra-vars @/srv/provisioning/tests/container/users.yml) ;;
    esac
    in_container env ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg ansible-pull \
        --url /srv/provisioning --checkout main --directory /opt/sandbox-provisioning \
        --inventory inventories/local/hosts.yml "${extra[@]}" "$play.yml"
}

recap() { grep -E '^localhost +: ok=' "$1" | tail -1; }
count() { recap "$1" | sed -E "s/.* $2=([0-9]+).*/\1/"; }

# Apply every play once; the run is named by $1 (first, second).
apply() {
    local run=$1 play
    for play in $plays; do
        if ! apply_play "$play" >"$logs/$run.$play.log" 2>&1; then
            tail -60 "$logs/$run.$play.log"
            echo "FAILED: the $run apply of $play.yml did not finish; full log in $logs/$run.$play.log"
            return 1
        fi
        echo "   $play.yml: $(recap "$logs/$run.$play.log")"
    done
}

echo "== first apply (plays: $plays; roles of site.yml: $roles)"
apply first || exit 1

echo "== second apply"
apply second || exit 1
for play in $plays; do
    if [ "$(count "$logs/second.$play.log" changed)" != 0 ]; then
        grep -B1 -A6 '^changed:' "$logs/second.$play.log" | head -80
        echo "FAILED: the second apply of $play.yml changed something"
        exit 1
    fi
done

# Stage 11: the three roles that reach Spack through the csis_spack collection
# can be previewed. After two applies a preview must find nothing to change.
check_roles=""
for role in spack intel_oneapi spack_environment; do
    case ",$roles," in *",$role,"*) check_roles="${check_roles:+$check_roles,}$role" ;; esac
done
case " $plays " in
    *" site "*)
        if [ -n "$check_roles" ]; then
            echo "== check mode (roles: $check_roles)"
            # shellcheck disable=SC2016 # $1 is expanded by the shell in the container
            if ! in_container bash -c 'cd /opt/sandbox-provisioning && ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg exec ansible-playbook --inventory inventories/local/hosts.yml --extra-vars @/srv/provisioning/tests/container/vars.yml --check --tags "$1" site.yml' _ "$check_roles" \
                >"$logs/check.log" 2>&1; then
                tail -60 "$logs/check.log"
                echo "FAILED: check mode did not finish; full log in $logs/check.log"
                exit 1
            fi
            echo "   site.yml --check: $(recap "$logs/check.log")"
            if [ "$(count "$logs/check.log" changed)" != 0 ]; then
                grep -B1 -A6 '^changed:' "$logs/check.log" | head -80
                echo "FAILED: check mode after two applies would change something"
                exit 1
            fi
        fi
        ;;
esac

echo "== checking what the roles left behind"
# shellcheck disable=SC2016 # $1 is expanded by the shell in the container
# As JSON: given as key=value, a value with spaces is cut at the first one,
# so "site users jupyterhub" became "site" and the checks of users.yml and
# jupyterhub.yml were skipped, with the run still passing (found in stage 13).
if ! in_container bash -c 'cd /opt/sandbox-provisioning && exec ansible-playbook tests/container/verify.yml --extra-vars "{\"verify_plays\": \"$1\"}"' _ "$plays" \
    >"$logs/verify.log" 2>&1; then
    tail -60 "$logs/verify.log"
    echo "FAILED: the result is not what the roles should leave"
    exit 1
fi
grep -E 'OBSERVED|^localhost +: ok=' "$logs/verify.log" | sed -E 's/^ *(msg: )?/   /'
# Every play asked for must have been checked: a play skipped for want of a
# host is a test that did not run.
skipped=$(grep -c 'skipping: no hosts matched' "$logs/verify.log" || true)
expected_skips=$((3 - $(wc -w <<<"$plays")))
if [ "$skipped" != "$expected_skips" ]; then
    grep -B1 'skipping: no hosts matched' "$logs/verify.log"
    echo "FAILED: $skipped of verify.yml's plays were skipped; with plays '$plays', $expected_skips should be"
    exit 1
fi

# Spec 002: push-build-cache.yml against a build cache in a directory,
# unsigned (the container has no signing key). Spack refuses to push an
# environment any of whose packages is not installed, and the site's
# environment is only concretized here, so the push is of an environment of
# its own: one small package, zlib-ng, fake-installed. A fake install leaves
# out build-only dependencies, which the push also sends, so the one it needs,
# compiler-wrapper, is a root of its own there.
case " $plays " in
    *" site "*)
        case ",$roles," in
            *",spack_environment,"*)
                echo "== pushing the environment to a build cache in a directory (spec 002)"
                # shellcheck disable=SC2016 # expanded by the shell in the container
                if ! in_container sudo -u ec2-user bash -c '
                    set -e
                    spack=$(ls /save/environments/spack.*/bin/spack)
                    "$spack" env create --dir /tmp/push-env
                    "$spack" -e /tmp/push-env add zlib-ng compiler-wrapper
                    "$spack" -e /tmp/push-env concretize
                    "$spack" -e /tmp/push-env install --fake
                ' >"$logs/fake-install.log" 2>&1; then
                    tail -30 "$logs/fake-install.log"
                    echo "FAILED: the fake install for the push did not finish; full log in $logs/fake-install.log"
                    exit 1
                fi
                # $1: unsigned or not; the rest: more arguments for ansible-playbook.
                push() {
                    # shellcheck disable=SC2016 # $1 and $@ are expanded by the shell in the container
                    in_container bash -c 'cd /opt/sandbox-provisioning && ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg exec ansible-playbook --inventory inventories/local/hosts.yml --extra-vars @/srv/provisioning/tests/container/vars.yml --extra-vars "{\"spack_mirror\": \"/tmp/build-cache\", \"spack_environment_dir\": \"/tmp/push-env\", \"push_build_cache_unsigned\": $1}" "${@:2}" push-build-cache.yml' _ "$@"
                }
                cached() { in_container bash -c 'find /tmp/build-cache -type f 2>/dev/null | wc -l'; }
                for run in check first second; do
                    extra=()
                    [ "$run" = check ] && extra=(--check)
                    if ! push true "${extra[@]}" >"$logs/push.$run.log" 2>&1; then
                        tail -40 "$logs/push.$run.log"
                        # shellcheck disable=SC2016 # expanded by the shell in the container
                        in_container sudo -u ec2-user bash -c '"$(ls /save/environments/spack.*/bin/spack)" -e /tmp/push-env spec -I -t -L' || true
                        echo "FAILED: the $run push did not finish; full log in $logs/push.$run.log"
                        exit 1
                    fi
                    echo "   push-build-cache.yml ($run): $(recap "$logs/push.$run.log"); files in the cache: $(cached)"
                    changed=$(count "$logs/push.$run.log" changed)
                    case "$run" in
                        check)
                            [ "$changed" != 0 ] && [ "$(cached)" = 0 ] ||
                                { echo "FAILED: check mode must report the missing package and push nothing"; exit 1; } ;;
                        first)
                            [ "$changed" != 0 ] && [ "$(cached)" != 0 ] ||
                                { echo "FAILED: the first push must push the package"; exit 1; } ;;
                        second)
                            [ "$changed" = 0 ] ||
                                { grep -B1 -A6 '^changed:' "$logs/push.$run.log" | head -40; echo "FAILED: the second push changed something"; exit 1; } ;;
                    esac
                done
                # Signed, with no signing key in Spack's keyring: it must stop
                # before pushing, and name the key.
                if push false >"$logs/push.nokey.log" 2>&1; then
                    echo "FAILED: a signed push without the key went through"
                    exit 1
                fi
                fingerprint=$(sed -nE 's/^spack_key_fingerprint: *([0-9A-F]{40}).*/\1/p' "$unit/group_vars/all.yml")
                grep -q "$fingerprint" "$logs/push.nokey.log" ||
                    { tail -20 "$logs/push.nokey.log"; echo "FAILED: the refusal does not name the key"; exit 1; }
                echo "   a signed push without the key stops, naming it"
                # The old site's bucket is never written to (spec 002, FR-008): a
                # push aimed there stops before anything is sent.
                if push true --extra-vars spack_mirror=s3://ioos-cloud-sandbox/public/spack/mirror \
                    >"$logs/push.ioos.log" 2>&1; then
                    echo "FAILED: a push to ioos-cloud-sandbox went through"
                    exit 1
                fi
                grep -q "is never written to" "$logs/push.ioos.log" ||
                    { tail -20 "$logs/push.ioos.log"; echo "FAILED: the refusal does not say why"; exit 1; }
                echo "   a push to ioos-cloud-sandbox stops before sending anything"
                ;;
        esac
        ;;
esac

case " $plays " in
    *" users "*)
        echo "== removing the test user"
        if ! in_container env ANSIBLE_CONFIG=/opt/sandbox-provisioning/ansible.cfg bash -c '
            cd /opt/sandbox-provisioning &&
            ansible-playbook -i inventories/local/hosts.yml users.yml \
                -e "{\"sandbox_users_present\": [], \"sandbox_users_absent\": [\"jdoe\"]}" &&
            ! id jdoe 2>/dev/null && ! getent group jdoe && [ ! -e /home/jdoe ]' >"$logs/remove.log" 2>&1; then
            tail -40 "$logs/remove.log"
            echo "FAILED: the test user was not removed"
            exit 1
        fi
        echo "   jdoe, the group and the home directory are gone"
        ;;
esac

echo "PASSED: applied twice, second run changed nothing, result verified"
