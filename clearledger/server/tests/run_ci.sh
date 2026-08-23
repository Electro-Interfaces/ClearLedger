#!/usr/bin/env bash
# Прогон тестов для проверок: файл за файлом, с карантином.
#
# Файлы гоняются порознь и каждый со своей чистой базой. Набор пока зависит от
# порядка — тест видит компанию и документы, заведённые соседним файлом, и
# падает не по своей вине. Пока это не вычищено, честнее гонять файлы отдельно,
# чем читать случайные падения общего прогона; сам порядок — отдельный долг.
#
# Тот же скрипт гоняется руками на стенде: одна команда вместо цикла в голове.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

quarantine="tests/quarantine.txt"
# Строка карантина с `::` — отдельный тест, без `::` — файл целиком.
mapfile -t deselect < <(grep -E '::' "$quarantine" | grep -v '^#' | sed 's/^/--deselect=/')

failed=""
for file in tests/test_*.py; do
  if grep -qxF "$file" "$quarantine"; then
    echo "карантин, пропущен: $file"
    continue
  fi
  echo "── $file"
  python -m pytest "$file" -q -p no:cacheprovider "${deselect[@]}" || failed="$failed $file"
done

if [ -n "$failed" ]; then
  echo "красные файлы:$failed"
  exit 1
fi
echo "все файлы зелёные"
