#!/bin/bash
# QA 앱 시작 — Finder 에서 두 번 누른다. 처음이거나 구성요소가 바뀌었으면 설치부터 한다
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/app" || exit 1
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js(npm) 가 없습니다. 터미널에서 brew install node 를 실행한 뒤 다시 누르세요."
  read -r -p "Enter 를 누르면 닫습니다"; exit 1
fi
if [ ! -d node_modules ] || [ package-lock.json -nt node_modules/.package-lock.json ]; then
  echo "QA 앱 구성요소를 설치합니다(처음 한 번, 몇 분 걸립니다)…"
  npm ci --no-audit --no-fund || { read -r -p "설치 실패 — Enter 를 누르면 닫습니다"; exit 1; }
fi
nohup npm start >/dev/null 2>&1 &
echo "QA 앱을 띄웠습니다. 이 창은 닫아도 됩니다."
