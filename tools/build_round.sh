# Builds every hole of a course into game/courses/<course>/<NN>/ and writes the course list the game reads.
#   bash tools/build_round.sh tilgate-forest "Tilgate Forest"     (4 holes at a time; ~3 min per hole)
# Holes are procedural: shape from the GPS tee/layup/green, standard bunkers, ponds and streams.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; COURSE="$1"; NAME="${2:-$1}"
ls "$ROOT/data/$COURSE"-[0-9]*.json | sed 's|.*/||; s|\.json$||' |
  xargs -P "${JOBS:-4}" -I{} sh -c 'n=${1##*-}; HOLE=$1 OUT="$2/game/courses/$3/$n" bash "$2/tools/build_course.sh" > "$2/build/$1.log" 2>&1 && echo "built $1" || { echo "FAILED $1 (see build/$1.log)"; exit 255; }' _ {} "$ROOT" "$COURSE"
python3 "$ROOT/tools/course_index.py" "$COURSE" "$NAME"
