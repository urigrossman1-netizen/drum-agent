#!/usr/bin/env bash
# Install the official LilyPond binary release (no root needed if PREFIX is writable).
#
#   scripts/install_lilypond.sh            # installs 2.26.0 into /opt
#   PREFIX=$HOME/.local scripts/install_lilypond.sh
#
# Then either keep the default location (/opt/lilypond-<ver>/bin/lilypond is
# found automatically) or export DRUM_AGENT_LILYPOND=<prefix>/lilypond-<ver>/bin/lilypond.
set -euo pipefail

VERSION="${LILYPOND_VERSION:-2.26.0}"
PREFIX="${PREFIX:-/opt}"
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) ASSET="lilypond-${VERSION}-linux-x86_64.tar.gz"
                SHA256="cd8a097a9f52cb2b9f4e7914774786f203f4fc61fcd299afcbb63c23fa5c6b24" ;;
  Darwin-*)     ASSET="lilypond-${VERSION}-darwin-x86_64.tar.gz"  # runs under Rosetta on Apple silicon
                SHA256="6dcbca34b13ad6d4ba3606a0b48edd02688284fcd52e9c00141242df1996a148" ;;
  *) echo "No official binary for $(uname -s)-$(uname -m); use your package manager (lilypond >= 2.24)." >&2; exit 1 ;;
esac
[ "${VERSION}" = "2.26.0" ] || SHA256=""  # the checksums above are 2.26.0's
URL="https://gitlab.com/lilypond/lilypond/-/releases/v${VERSION}/downloads/${ASSET}"

if [ -x "${PREFIX}/lilypond-${VERSION}/bin/lilypond" ]; then
  echo "LilyPond ${VERSION} already installed at ${PREFIX}/lilypond-${VERSION}"
  exit 0
fi
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Downloading ${URL}"
# A stalled transfer (under 10 kB/s for a minute) counts as a failure, so it is retried.
curl -fsSL --retry 3 --connect-timeout 30 --speed-limit 10240 --speed-time 60 -o "${tmp}/${ASSET}" "${URL}"
if [ -n "${SHA256}" ]; then
  sum="sha256sum"
  command -v sha256sum > /dev/null || sum="shasum -a 256"
  echo "${SHA256}  ${tmp}/${ASSET}" | ${sum} -c - > /dev/null || { echo "${ASSET}: not the expected file" >&2; exit 1; }
else
  echo "warning: no checksum recorded for LilyPond ${VERSION}" >&2
fi
mkdir -p "${PREFIX}"
# Unpack beside the final place and move it there in one step: an interrupted install never
# leaves a lilypond executable without the rest of LilyPond (the check above would trust it).
stage="$(mktemp -d "${PREFIX}/.lilypond-${VERSION}.XXXXXX")"
trap 'rm -rf "$tmp" "$stage"' EXIT
tar -xzf "${tmp}/${ASSET}" -C "${stage}"
rm -rf "${PREFIX:?}/lilypond-${VERSION}"  # what is there has no lilypond executable: incomplete
mv "${stage}/lilypond-${VERSION}" "${PREFIX}/"
"${PREFIX}/lilypond-${VERSION}/bin/lilypond" --version | head -1
echo "Installed. Check with: python -m drum_agent doctor"
