#!/usr/bin/env bash
# Прогон тестов для проверок: файл за файлом, с карантином.
#
# Файлы гоняются порознь и каждый со своей чистой базой. Набор пока зависит от
# порядка — тест видит компанию и документы, заведённые соседним файлом, и
# падает не по своей вине. Пока это не вычищено, честнее гонять файлы отдельно,
# чем читать случайные падения общего прогона; сам порядок — отдельный долг.
#
# Тот же скрипт гоняется руками на стенде: одна команда вместо цикла в голове.
#
# Зелёный прогон на стенде НЕ означает зелёный CI, и об этом скрипт теперь
# говорит вслух. Часть проверок отключает себя сама, когда окружения нет: одни
# сверяются с деревом фронта, другие ищут Postgres на localhost. В контейнере
# стенда нет ни того, ни другого — такие файлы молча показывали «skipped», и две
# настоящие поломки прожили так неделю, краснея только в CI. Чтобы прогон на
# стенде был полноценным, монтируйте дерево целиком и ставьте базу на localhost:
#
#   docker run --rm --network container:<стек>-support-db \
#     -v /opt/ledger-src/clearledger:/app -w /app/server \
#     -e TEST_DATABASE_URL=postgresql+asyncpg://…@127.0.0.1:5432/clearledger_test \
#     <образ> sh -c "pip install -q pytest pytest-asyncio; bash tests/run_ci.sh"
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

quarantine="tests/quarantine.txt"
# Строка карантина с `::` — отдельный тест, без `::` — файл целиком.
mapfile -t deselect < <(grep -E '::' "$quarantine" | grep -v '^#' | sed 's/^/--deselect=/')

failed=""
skipped_files=""
for file in tests/test_*.py; do
  if grep -qxF "$file" "$quarantine"; then
    echo "карантин, пропущен: $file"
    continue
  fi
  echo "── $file"
  out=$(python -m pytest "$file" -q -p no:cacheprovider "${deselect[@]}" 2>&1)
  status=$?
  echo "$out"
  [ $status -eq 0 ] || failed="$failed $file"
  # Файл, где не выполнилось НИ ОДНОГО теста, проверкой не был. Итоговая строка
  # pytest начинается с числа пройденных, если хоть один прошёл, — значит строка
  # вида «N skipped» без «passed» и означает файл, отключённый целиком.
  if echo "$out" | grep -qE '^[0-9]+ skipped'; then
    skipped_files="$skipped_files $file"
  fi
done

if [ -n "$skipped_files" ]; then
  echo
  echo "проверок не было (окружение отключило файл целиком):$skipped_files"
  echo "в CI эти файлы гоняются — зелёный прогон здесь не заменяет зелёный CI"
fi

if [ -n "$failed" ]; then
  echo "красные файлы:$failed"
  exit 1
fi
echo "все файлы зелёные"
