#!/bin/sh
# Install the custom integration; retain the previous version on updates.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
source_dir="$script_dir/../custom_components/mammotion_openapi"
source_dir=$(CDPATH= cd -- "$source_dir" && pwd -P)
target=${1:-/config/custom_components/mammotion_openapi}
target=${target%/}

if [ "$#" -gt 1 ] || [ "$(basename -- "$target")" != mammotion_openapi ] ||
   [ "$(basename -- "$(dirname -- "$target")")" != custom_components ]; then
    echo "Usage: sh $0 [/config/custom_components/mammotion_openapi]" >&2
    exit 1
fi

if [ -L "$target" ] || { [ -e "$target" ] && [ ! -d "$target" ]; }; then
    echo "Refusing to replace a symlink or non-directory: $target" >&2
    exit 1
fi

mkdir -p -- "$(dirname -- "$target")"
target_parent=$(CDPATH= cd -- "$(dirname -- "$target")" && pwd -P)
target="$target_parent/mammotion_openapi"
if [ "$target" = "$source_dir" ]; then
    echo "Choose the Home Assistant destination, not the source checkout." >&2
    exit 1
fi

lock="$target_parent/.mammotion_openapi.install.lock"
if ! mkdir -- "$lock"; then
    echo "Another installation may be running; check $lock before trying again." >&2
    exit 1
fi

stage=
backup=
cleanup() {
    result=$?
    trap - 0 HUP INT TERM
    if [ "$result" -ne 0 ] && [ -n "$backup" ] &&
       [ -d "$backup/mammotion_openapi" ] && [ ! -e "$target" ]; then
        if mv -- "$backup/mammotion_openapi" "$target"; then
            rmdir -- "$backup"
        else
            echo "Restore the previous integration from $backup/mammotion_openapi" >&2
        fi
    fi
    if [ -n "$stage" ] && [ -d "$stage" ]; then
        rm -rf -- "$stage"
    fi
    rmdir -- "$lock"
    exit "$result"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM

stage=$(mktemp -d "$target_parent/.mammotion_openapi.install.XXXXXX")
cp -- "$source_dir"/*.py "$source_dir"/*.json "$source_dir"/*.yaml "$stage/"
mkdir -- "$stage/translations"
cp -- "$source_dir"/translations/*.json "$stage/translations/"

if [ -d "$target" ]; then
    backup=$(mktemp -d "$target_parent/.mammotion_openapi.backup.XXXXXX")
    mv -- "$target" "$backup/mammotion_openapi"
fi
mv -- "$stage" "$target"
stage=

echo "Installed Mammotion Open API in $target"
if [ -n "$backup" ]; then
    echo "Previous version saved in $backup/mammotion_openapi"
fi
echo "Restart Home Assistant, then add Mammotion Open API under Devices & services."
