#!/usr/bin/env bash
# Builds the audio tools the browser build runs, as WebAssembly: fpcalc,
# ffprobe, and sdm_ffmpeg (this folder's sdm_ffmpeg.c).
#
# Natively `duplicates` and `rekordbox` run fpcalc, and `quality` runs ffprobe
# and ffmpeg, as processes. A tab has no processes, so frontend/src/browser/
# tools.ts instantiates these modules afresh for every run instead, and Python
# reaches them through sdm.core.tools's `runner` hook with the same argv.
#
#   fpcalc       Chromaprint 1.6.1's own fpcalc.cpp - the release
#                core/fpcalc_fetch.py borrows natively - built as Chromaprint's
#                release builds are: FFmpeg's av_tx FFT and swresample.
#   ffprobe      FFmpeg 7.1.1's own ffprobe, the version `quality` was measured
#                with natively.
#   sdm_ffmpeg   The one ffmpeg command line `quality` runs, on the same 7.1.1
#                libraries. Not ffmpeg itself: since 6.0 that needs threads, and
#                these run single-threaded and synchronously. See sdm_ffmpeg.c.
#
# Run on Linux or in WSL, and not on /mnt/c: it builds in $WORK (the home
# directory by default), because building FFmpeg across the Windows mount is
# several times slower. Only the output files are copied out.
#
#   wasm/build.sh [OUT_DIR]       default OUT_DIR: wasm/prebuilt/
#
# wasm/prebuilt/ is committed: Cloudflare's build runs build_browser.py but has
# no Emscripten, so it ships the modules from the repository. Commit them after
# every run. stamp.json beside them records what they were built from, and
# build_browser.py refuses to ship them once a source here has changed.
#
# Pinned and hash-checked: Emscripten (the release Pyodide 314 is built with),
# FFmpeg and Chromaprint. The Emscripten glue is patched once, below, and the
# patch is checked to apply. Audio only - AUDIO_EXTS's containers and codecs
# (core/track.py), the cover-art decoders a probe meets, the filters `quality`
# uses - so each module is a few MB, under Cloudflare's 25 MiB per-file limit
# that the stock ffmpeg.wasm (~31 MB) is not. LGPL: no --enable-gpl, no
# nonfree; Chromaprint is MIT. This script is the corresponding source.
set -euo pipefail

EMSDK_VERSION=5.0.3
FFMPEG_VERSION=7.1.1
FFMPEG_SHA256=733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1
CHROMAPRINT_VERSION=1.6.1
CHROMAPRINT_SHA256=3368805af0ee47b9df74df10b5001a44569e01df2844dab520031720dde9ad23

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/prebuilt}"
WORK="${WORK:-$HOME/.cache/sdm-ffmpeg-wasm}"
PREFIX="$WORK/prefix"
JOBS="$(nproc)"
mkdir -p "$WORK" "$PREFIX" "$OUT"

fetch() {  # url, sha256, file
  [ -f "$WORK/$3" ] || curl -fsSL "$1" -o "$WORK/$3"
  if ! echo "$2  $WORK/$3" | sha256sum -c --quiet; then
    echo "wasm/build.sh: $3 does not match its pinned sha256" >&2
    rm -f "$WORK/$3"
    exit 1
  fi
}

# --- Emscripten ------------------------------------------------------------------------
[ -d "$WORK/emsdk" ] || git clone -q https://github.com/emscripten-core/emsdk.git "$WORK/emsdk"
(cd "$WORK/emsdk" && ./emsdk install "$EMSDK_VERSION" >/dev/null && ./emsdk activate "$EMSDK_VERSION" >/dev/null)
# shellcheck disable=SC1091
source "$WORK/emsdk/emsdk_env.sh" >/dev/null 2>&1
emcc --version | head -1

# --- FFmpeg libraries, and ffprobe's objects -------------------------------------------
fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256" "ffmpeg-$FFMPEG_VERSION.tar.xz"
FF="$WORK/ffmpeg-build-$FFMPEG_VERSION"
if [ ! -f "$PREFIX/lib/libavformat.a" ]; then
  rm -rf "$FF" && mkdir -p "$FF"
  tar -xJf "$WORK/ffmpeg-$FFMPEG_VERSION.tar.xz" -C "$FF" --strip-components=1
  cd "$FF"
  emconfigure ./configure \
    --prefix="$PREFIX" --target-os=none --arch=x86_32 --enable-cross-compile \
    --cc=emcc --cxx=em++ --ar=emar --ranlib=emranlib --nm=emnm \
    --disable-asm --disable-x86asm --disable-inline-asm --disable-stripping \
    --disable-doc --disable-debug --disable-runtime-cpudetect --disable-autodetect \
    --disable-pthreads --disable-w32threads --disable-os2threads --disable-network \
    --disable-everything --disable-avdevice --disable-swscale --disable-postproc \
    --disable-ffmpeg --disable-ffplay --enable-ffprobe \
    --enable-zlib \
    --enable-protocol=file,pipe \
    --enable-demuxer=mp3,mov,flac,wav,aiff,ogg,aac,w64 \
    --enable-decoder=mp3float,mp3,mp2float,mp1float,aac,aac_latm,alac,flac,vorbis,opus \
    --enable-decoder=pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be \
    --enable-decoder=pcm_f32le,pcm_f32be,pcm_f64le,pcm_f64be,pcm_u8,pcm_s8,pcm_alaw,pcm_mulaw \
    --enable-decoder=mjpeg,png,bmp,gif \
    --enable-parser=mpegaudio,aac,aac_latm,flac,vorbis,opus,mjpeg,png \
    --enable-filter=abuffer,abuffersink,aformat,aresample,anull,ebur128 \
    --extra-cflags="-O3 -sUSE_ZLIB=1" --extra-ldflags="-sUSE_ZLIB=1" >/dev/null
  emmake make -j "$JOBS" >/dev/null
  emmake make install >/dev/null
fi

# --- Chromaprint, against those libraries ----------------------------------------------
fetch "https://github.com/acoustid/chromaprint/releases/download/v$CHROMAPRINT_VERSION/chromaprint-$CHROMAPRINT_VERSION.tar.gz" \
  "$CHROMAPRINT_SHA256" "chromaprint-$CHROMAPRINT_VERSION.tar.gz"
CP="$WORK/chromaprint-build-$CHROMAPRINT_VERSION"
if [ ! -f "$PREFIX/lib/libchromaprint.a" ]; then
  rm -rf "$CP" && mkdir -p "$CP"
  tar -xzf "$WORK/chromaprint-$CHROMAPRINT_VERSION.tar.gz" -C "$CP" --strip-components=1
  emcmake cmake -S "$CP" -B "$CP/build" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_TOOLS=OFF -DBUILD_TESTS=OFF \
    -DFFT_LIB=avtx -DAUDIO_PROCESSOR_LIB=swresample \
    -DCMAKE_PREFIX_PATH="$PREFIX" -DCMAKE_FIND_ROOT_PATH="$PREFIX" \
    -DFFMPEG_ROOT="$PREFIX" -DCMAKE_INSTALL_PREFIX="$PREFIX" >/dev/null
  cmake --build "$CP/build" -j "$JOBS" >/dev/null
  cmake --install "$CP/build" >/dev/null
fi

# --- Link: one module per program ------------------------------------------------------
# Instantiated afresh per run (tools.ts): a program's globals are per process,
# and a fresh instance is a fresh process. Synchronously, because Python calls
# in synchronously: WASM_ASYNC_COMPILATION=0, and worker-only, since the Node
# glue awaits an import before anything else. EXIT_RUNTIME flushes stdio when
# main returns, which ffprobe's JSON and fpcalc's output need. 5 MB of stack,
# as ffmpeg.wasm uses.
LINK=(
  -O3 -sUSE_ZLIB=1
  -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createTool
  -sENVIRONMENT=worker -sWASM_ASYNC_COMPILATION=0
  -sINVOKE_RUN=0 -sEXIT_RUNTIME=1
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=33554432 -sSTACK_SIZE=5242880
  -sFORCE_FILESYSTEM=1 -lworkerfs.js
  -sEXPORTED_RUNTIME_METHODS=callMain,FS
)
LIBS=(
  "$PREFIX/lib/libavfilter.a" "$PREFIX/lib/libavformat.a" "$PREFIX/lib/libavcodec.a"
  "$PREFIX/lib/libswresample.a" "$PREFIX/lib/libavutil.a"
)
mkdir -p "$WORK/out"

em++ "${LINK[@]}" -o "$WORK/out/ffprobe.mjs" \
  "$FF/fftools/ffprobe.o" "$FF/fftools/cmdutils.o" "$FF/fftools/opt_common.o" "${LIBS[@]}"

emcc -O3 -sUSE_ZLIB=1 -I"$PREFIX/include" -c "$HERE/sdm_ffmpeg.c" -o "$WORK/sdm_ffmpeg.o"
em++ "${LINK[@]}" -o "$WORK/out/sdm_ffmpeg.mjs" "$WORK/sdm_ffmpeg.o" "${LIBS[@]}"

em++ -O3 -std=c++11 -DHAVE_CONFIG_H -I"$CP/build" -I"$CP/src" -I"$PREFIX/include" \
  -c "$CP/src/cmd/fpcalc.cpp" -o "$WORK/fpcalc.o"
em++ "${LINK[@]}" -o "$WORK/out/fpcalc.mjs" "$WORK/fpcalc.o" "$PREFIX/lib/libchromaprint.a" "${LIBS[@]}"

# The glue compiles the wasm in `instantiateSync` on every instantiation;
# reuse the module tools.ts compiled once, passed as Module.wasmModule.
# Instantiating is then ~2 ms, where compiling each time costs more per track
# than fingerprinting it.
python3 - "$WORK"/out/*.mjs <<'PY'
import sys
OLD = "function instantiateSync(file,info){var module;var binary=getBinarySync(file);module=new WebAssembly.Module(binary);"
NEW = 'function instantiateSync(file,info){var module=Module["wasmModule"]??new WebAssembly.Module(getBinarySync(file));'
for path in sys.argv[1:]:
    text = open(path, encoding="utf-8").read()
    if text.count(OLD) != 1:
        sys.exit(f"wasm/build.sh: the Emscripten glue in {path} changed; update the patch")
    open(path, "w", encoding="utf-8").write(text.replace(OLD, NEW))
PY

# The stamp: sources and modules by sha256, the sources read with CRLF as LF,
# since a Windows checkout may convert what Cloudflare's does not. Hashed and
# checked as build_browser.py does (TOOL_SOURCES there is SOURCES here). Removed
# before the copy, so an interrupted one leaves no stamp vouching for it.
rm -f "$OUT/stamp.json"
cp "$WORK"/out/*.mjs "$WORK"/out/*.wasm "$OUT/"
python3 - "$HERE" "$OUT" <<'PY'
import hashlib, json, sys
from pathlib import Path
here, out = Path(sys.argv[1]), Path(sys.argv[2])
SOURCES = ("build.sh", "sdm_ffmpeg.c")
stamp = {
    "sources": {name: hashlib.sha256((here / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                for name in SOURCES},
    "outputs": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted([*out.glob("*.mjs"), *out.glob("*.wasm")])},
}
(out / "stamp.json").write_text(json.dumps(stamp, indent=1) + "\n", encoding="utf-8")
PY
ls -l "$OUT"
