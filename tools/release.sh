#!/bin/bash
# Cut a release in the only order that works: bump, audit, commit, tag, push,
# then package from the tarball the tag actually produced. Doing it by hand
# once tagged before bumping, and the package said 1.0.1 while the binary in
# it said 1.0.0; nothing in the toolchain noticed. Step 7 here would have.
#
#   tools/release.sh 1.2.0             # the real thing
#   tools/release.sh 1.2.0 --dry-run   # every check, no commit, tag or push;
#                                      # every file put back afterwards
#
# It pushes the bump commit and the tag. It does not push the packaging commit
# and it never touches the AUR; both are yours. Stops at the first failure.
#
# Knobs for testing the script itself, never for a release:
#   AUDIT=path         a different audit (a failing one proves the gate)
#   RELEASE_URL=base   where "$base/archive/refs/tags/vX.tar.gz" is fetched
#                      from instead of the PKGBUILD's url= (file:// works)
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
audit=${AUDIT:-tools/audit.py}
version=${1:-}
dry=0; [[ ${2:-} == --dry-run ]] && dry=1

n=0
step() { n=$((n + 1)); printf '\n==> %d. %s\n' "$n" "$*"; }
die()  { printf '\nrelease.sh: %s\n' "$*" >&2; exit 1; }

# Files this run has changed and not committed. On any exit they go back;
# after the bump commit yoru.py leaves the list, and in a real run the
# packaging edits are left in place on failure so you can see them.
restore=()
cleanup() {
  local rc=$?
  if ((${#restore[@]})); then
    git checkout -q -- "${restore[@]}"
    echo "   (restored: ${restore[*]})"
  fi
  exit "$rc"
}
trap cleanup EXIT

# -- preflight -----------------------------------------------------------------
step "Preflight for ${version:-<none>}"
[[ -n $version ]] || die "usage: tools/release.sh X.Y.Z [--dry-run]"
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$version' is not X.Y.Z"
tag="v$version"
[[ $(git branch --show-current) == main ]] || die "not on main"
[[ -z $(git status --porcelain --untracked-files=no) ]] || die "working tree is dirty; commit or stash first"
git fetch -q --tags origin
[[ $(git rev-parse HEAD) == $(git rev-parse origin/main) ]] || die "main is not in sync with origin/main"
! git rev-parse -q --verify "refs/tags/$tag" >/dev/null || die "$tag already exists locally"
[[ -z $(git ls-remote --tags origin "refs/tags/$tag") ]] || die "$tag already exists on origin"
current=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' yoru.py)
[[ $current != "$version" ]] || die "yoru.py already says $version; nothing to release"
url=$(sed -n 's/^url="\(.*\)"$/\1/p' PKGBUILD)
[[ -n $url ]] || die "no url= in PKGBUILD"
base=${RELEASE_URL:-$url}
echo "   $current -> $version on $(git rev-parse --short HEAD); tarball from $base"
((dry)) && echo "   dry run: nothing will be committed, tagged or pushed"

# -- bump ----------------------------------------------------------------------
step "Set VERSION = \"$version\" in yoru.py"
sed -i "s/^VERSION = \"$current\"\$/VERSION = \"$version\"/" yoru.py
restore+=(yoru.py)
got=$(python3 yoru.py --version)
[[ $got == "yoru $version" ]] || die "yoru --version says '$got'"
echo "   yoru --version: $got"

step "Audit ($audit)"
out=$(python3 "$audit" 2>&1) || die "audit exited non-zero:"$'\n'"$out"
last=$(printf '%s\n' "$out" | tail -1)
echo "   $last"
[[ $last == *"FAILURES: none"* ]] || die "audit failed:"$'\n'"$(printf '%s\n' "$out" | grep '^  FAIL')"

step "Commit the bump on its own"
if ((dry)); then
  echo "   (dry run) would: git commit yoru.py -m 'Bump VERSION to $version'"
else
  git add yoru.py
  git commit -q -m "Bump VERSION to $version"
  restore=()                               # committed; nothing to put back
  echo "   $(git log -1 --format='%h %s')"
fi

step "Tag $tag and push main and the tag"
if ((dry)); then
  echo "   (dry run) would: git tag -a $tag; git push origin main $tag"
else
  git tag -a "$tag" -m "Yoru $version"
  git push -q origin main "$tag"
  echo "   $tag -> $(git rev-parse --short "$tag^{}")"
fi

# -- package -------------------------------------------------------------------
step "Fetch the tarball built for $tag"
work=$(mktemp -d --tmpdir yoru-release.XXXXXX)
tarball="$work/yoru-$version.tar.gz"     # the name PKGBUILD's source= gives it
for try in $(seq 1 10); do
  curl -sSfL -o "$tarball" "$base/archive/refs/tags/$tag.tar.gz" && break
  ((try < 10)) || die "could not fetch $base/archive/refs/tags/$tag.tar.gz"
  sleep 3
done
sha=$(sha256sum "$tarball" | cut -d' ' -f1)
echo "   sha256 $sha"

step "Check the tarball's yoru.py says $version"
in_tar=$(tar -xOzf "$tarball" "yoru-$version/yoru.py" | sed -n 's/^VERSION = "\(.*\)"$/\1/p')
[[ $in_tar == "$version" ]] || die "the tarball's yoru.py says '$in_tar', not $version: the tag is on the wrong commit"
echo "   VERSION = \"$in_tar\""

step "Update PKGBUILD and regenerate .SRCINFO"
((dry)) && restore+=(PKGBUILD .SRCINFO)
sed -i -e "s/^pkgver=.*/pkgver=$version/" -e "s/^pkgrel=.*/pkgrel=1/" \
       -e "s/^sha256sums=.*/sha256sums=('$sha')/" PKGBUILD
makepkg --printsrcinfo > .SRCINFO
grep -E '^(pkgver|pkgrel|sha256sums)=' PKGBUILD | sed 's/^/   /'

step "Build with makepkg against that tarball"
build="$work/build"; mkdir -p "$build" "$work/pkg"
cp PKGBUILD yoru.install "$build/"
(cd "$build" && SRCDEST="$work" PKGDEST="$work/pkg" makepkg -f >"$work/makepkg.log" 2>&1) \
  || die "makepkg failed:"$'\n'"$(tail -20 "$work/makepkg.log")"
grep -E 'Validating|Passed|FAILED|Finished' "$work/makepkg.log" | sed 's/^/   /'
pkgfile="$work/pkg/yoru-$version-1-any.pkg.tar.zst"
[[ -f $pkgfile ]] || die "no $pkgfile"

step "Install into a throwaway root and check the binary's version"
root="$work/root"; mkdir -p "$root"
tar -C "$root" --zstd -xf "$pkgfile" --exclude='.PKGINFO' --exclude='.MTREE' \
    --exclude='.BUILDINFO' --exclude='.INSTALL'
pkgver=$(tar -xOf "$pkgfile" .PKGINFO | sed -n 's/^pkgver = \(.*\)-1$/\1/p')
binver=$(python3 "$root/usr/bin/yoru" --version)
echo "   .PKGINFO says $pkgver; usr/bin/yoru --version says '$binver'"
[[ $pkgver == "$version" && $binver == "yoru $version" ]] || die "package and binary disagree"

step "Commit the packaging files (not pushed)"
if ((dry)); then
  echo "   (dry run) would: git commit PKGBUILD .SRCINFO -m 'Package $version'"
  printf '\nDry run for %s passed every check. Artifacts in %s\n' "$tag" "$work"
else
  git add PKGBUILD .SRCINFO
  git commit -q -m "Package $version"
  echo "   $(git log -1 --format='%h %s')"
  printf '\nReleased %s. Left for you: git push origin main; the AUR.\nArtifacts in %s\n' "$tag" "$work"
fi
