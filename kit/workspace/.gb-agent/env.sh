# gb_device.py 가 iOS(devicectl) 명령 전에 읽는 환경 파일. Xcode 경로만 맞추면 된다.
# xcode-select 가 CommandLineTools 를 가리키면 devicectl 이 없으므로 /Applications 의 Xcode 를 찾는다.
if [ -z "$DEVELOPER_DIR" ]; then
  d="$(xcode-select -p 2>/dev/null)"
  case "$d" in
    ""|*CommandLineTools*)
      for x in /Applications/Xcode.app /Applications/Xcode*.app; do
        if [ -d "$x/Contents/Developer" ]; then d="$x/Contents/Developer"; break; fi
      done
      ;;
  esac
  export DEVELOPER_DIR="$d"
fi
