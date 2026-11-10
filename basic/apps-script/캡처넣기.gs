/**
 * CRO_버젼별 기본기능 — 결과 칸(「AOS 결과」·「iOS 결과」)에 캡처 그림을 넣는다.
 *
 * 결과 칸 글: 줄마다 「지점: https://drive.google.com/file/d/<id>/view」 (tools/basic_sheet.py 가 쓴다)
 * 이 스크립트: 그 링크의 Drive 파일을 칸 위 그림으로 결과 칸에 붙인다 — 글 아래에 가로로 나란히, 넘치면 다음 줄.
 *   칸 하나에 그림 여러 장이 들어간다(칸 안 그림은 한 장뿐이라 칸에 기준을 둔 칸 위 그림을 쓴다). 행 높이를 그림에 맞춘다.
 *   글(실행 기록·링크)은 그대로 둔다 — 자동 결과 표시와 다음 실행의 줄 합치기가 이 글을 읽는다.
 *   이미 같은 캡처가 붙어 있으면 건너뛴다. 링크가 바뀌면 그 칸의 예전 그림을 지우고 새로 붙인다.
 *
 * 설치(시트마다 한 번): 시트 「확장 프로그램 → Apps Script」에 이 파일 내용을 붙여 넣고 저장 → 시트를 새로 열면 메뉴 「QA」가 생긴다.
 *   처음 실행할 때 Drive·시트 권한을 한 번 허용한다. 스크립트는 실행한 사람 계정으로 Drive 파일을 읽는다(파일을 공개하지 않는다).
 * 자동으로: 메뉴 「QA → 5분마다 자동으로 넣기 켜기」 — 결과를 쓴 버전 탭들을 5분마다 훑어 새 캡처를 붙인다.
 *
 * 저장소 원본: basic/apps-script/캡처넣기.gs — 고치면 시트의 스크립트도 다시 붙여 넣는다.
 */

const QA_RESULT_HEADERS = ['AOS 결과', 'iOS 결과'];
const QA_TAG = 'qa-capture:';      // 붙인 그림의 대체 텍스트 제목 — 이 스크립트가 붙인 그림만 지운다
const QA_THUMB_W = 200;            // 그림 한 장의 너비(px)
const QA_GAP = 6;
const QA_LINE_H = 17;              // 글 한 줄 높이(px) — 그림을 글 아래에 둔다
const QA_SKIP_TABS = ['TC', '시트1'];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('QA')
    .addItem('캡처 넣기 (이 탭)', 'qaInsertCapturesActive')
    .addItem('캡처 넣기 (모든 결과 탭)', 'qaInsertCapturesAll')
    .addItem('캡처 다시 붙이기 (이 탭 — 붙인 그림을 지우고 새로)', 'qaReinsertCapturesActive')
    .addItem('캡처 상태 보기 (이 탭)', 'qaDebugActive')
    .addSeparator()
    .addItem('5분마다 자동으로 넣기 켜기', 'qaInstallTrigger')
    .addItem('자동으로 넣기 끄기', 'qaRemoveTrigger')
    .addToUi();
}

function qaInsertCapturesActive() {
  const n = qaInsertCaptures_(SpreadsheetApp.getActiveSheet());
  SpreadsheetApp.getActive().toast(`캡처 ${n.added}장 붙임 · 칸 ${n.cells}개 확인` + (n.errors.length ? ` · 실패 ${n.errors.length}` : ''), 'QA', 8);
  if (n.errors.length) SpreadsheetApp.getUi().alert('붙이지 못한 캡처\n\n' + n.errors.join('\n'));
}

function qaReinsertCapturesActive() {
  const sheet = SpreadsheetApp.getActiveSheet();
  let removed = 0;
  sheet.getImages().forEach((img) => {
    if ((img.getAltTextTitle() || '').indexOf(QA_TAG) === 0) { img.remove(); removed++; }
  });
  const n = qaInsertCaptures_(sheet);
  SpreadsheetApp.getActive().toast(`지운 그림 ${removed}장 · 새로 붙인 캡처 ${n.added}장 · 칸 ${n.cells}개` + (n.errors.length ? ` · 실패 ${n.errors.length}` : ''), 'QA', 10);
  if (n.errors.length) SpreadsheetApp.getUi().alert('붙이지 못한 캡처\n\n' + n.errors.join('\n'));
}

// 이 탭의 결과 칸 링크와 붙어 있는 그림(크기·위치)을 창으로 보여 준다 — 그림이 안 보일 때 원인 찾기
function qaDebugActive() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const lastCol = sheet.getLastColumn(), lastRow = sheet.getLastRow();
  const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const lines = [];
  QA_RESULT_HEADERS.forEach((h) => {
    const col = header.indexOf(h) + 1;
    if (!col) { lines.push(`「${h}」 열 없음`); return; }
    sheet.getRange(2, col, lastRow - 1, 1).getDisplayValues().forEach((t, i) => {
      const ids = qaDriveIds_(t[0] || '');
      if (ids.length) lines.push(`${sheet.getRange(i + 2, col).getA1Notation()} 링크 ${ids.length}개 · 행 높이 ${sheet.getRowHeight(i + 2)}`);
    });
  });
  const imgs = sheet.getImages();
  lines.push(`그림 ${imgs.length}장`);
  imgs.forEach((img) => {
    const a = img.getAnchorCell();
    lines.push(`${a.getA1Notation()} ${img.getAltTextTitle() || '(제목 없음)'} · ${img.getWidth()}×${img.getHeight()} · 위치 ${img.getAnchorCellXOffset()},${img.getAnchorCellYOffset()}`);
  });
  SpreadsheetApp.getUi().alert('캡처 상태\n\n' + lines.join('\n'));
}

function qaInsertCapturesAll() {
  let added = 0, errors = [];
  SpreadsheetApp.getActive().getSheets().forEach((sh) => {
    if (QA_SKIP_TABS.indexOf(sh.getName()) >= 0) return;
    const n = qaInsertCaptures_(sh);
    added += n.added;
    errors = errors.concat(n.errors.map((e) => `${sh.getName()}: ${e}`));
  });
  if (errors.length) console.warn(errors.join('\n'));
  return added;
}

function qaInsertCaptures_(sheet) {
  const out = {added: 0, cells: 0, errors: []};
  const lastRow = sheet.getLastRow(), lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return out;
  const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const cols = QA_RESULT_HEADERS.map((h) => header.indexOf(h) + 1).filter((c) => c > 0);
  if (!cols.length) return out;
  // 이 스크립트가 붙인 그림 — 칸(행,열)별로
  const placed = {};
  sheet.getImages().forEach((img) => {
    const title = img.getAltTextTitle() || '';
    if (title.indexOf(QA_TAG) !== 0) return;
    const a = img.getAnchorCell();
    const key = a.getRow() + ',' + a.getColumn();
    (placed[key] = placed[key] || []).push(img);
  });
  const need = {};   // 행 → 필요한 높이
  cols.forEach((col) => {
    const texts = sheet.getRange(2, col, lastRow - 1, 1).getDisplayValues();
    const width = sheet.getColumnWidth(col);
    const perRow = Math.max(1, Math.floor((width - QA_GAP) / (QA_THUMB_W + QA_GAP)));
    texts.forEach((t, i) => {
      const row = i + 2, text = t[0] || '';
      const ids = qaDriveIds_(text);
      const key = row + ',' + col;
      const have = (placed[key] || []).map((img) => img.getAltTextTitle().slice(QA_TAG.length));
      if (!ids.length && !have.length) return;
      out.cells++;
      const top = text.split('\n').length * QA_LINE_H + QA_GAP;
      if (ids.slice().sort().join(',') === have.slice().sort().join(',')) {
        // 이미 같은 캡처 — 위치만 다시 맞춘다(칸 글 줄 수·칸 너비가 바뀌었을 수 있다). 순서는 칸 글의 링크 순서
        const imgs = placed[key].slice().sort((a, b) =>
          ids.indexOf(a.getAltTextTitle().slice(QA_TAG.length)) - ids.indexOf(b.getAltTextTitle().slice(QA_TAG.length)));
        need[row] = Math.max(need[row] || 0, qaLayout_(imgs, top, perRow));
        return;
      }
      (placed[key] || []).forEach((img) => img.remove());
      let x = QA_GAP, y = top, lineH = 0, n = 0;
      ids.forEach((id) => {
        try {
          const blob = DriveApp.getFileById(id).getBlob();
          if (n > 0 && n % perRow === 0) { x = QA_GAP; y += lineH + QA_GAP; lineH = 0; }
          const img = sheet.insertImage(blob, col, row, x, y);
          // 넣은 직후 크기를 0 으로 돌려주는 때가 있다 — 그러면 가로 4:3 으로 둔다(0 크기 그림은 보이지 않는다)
          const w0 = img.getWidth(), h0 = img.getHeight();
          const h = w0 > 0 && h0 > 0 ? Math.round(h0 * QA_THUMB_W / w0) : Math.round(QA_THUMB_W * 3 / 4);
          img.setWidth(QA_THUMB_W).setHeight(h);
          img.setAltTextTitle(QA_TAG + id);
          x += QA_THUMB_W + QA_GAP;
          lineH = Math.max(lineH, h);
          n++;
          out.added++;
        } catch (e) {
          out.errors.push(`${sheet.getRange(row, col).getA1Notation()} ${id}: ${e.message}`);
        }
      });
      need[row] = Math.max(need[row] || 0, y + lineH + QA_GAP);
    });
  });
  Object.keys(need).forEach((r) => {
    const row = Number(r);
    if (sheet.getRowHeight(row) < need[r]) sheet.setRowHeight(row, need[r]);
  });
  return out;
}

// 칸 위 그림들을 글 아래(top)부터 한 줄에 perRow 장씩 놓는다. 필요한 행 높이를 돌려준다
function qaLayout_(images, top, perRow) {
  let x = QA_GAP, y = top, lineH = 0;
  images.forEach((img, n) => {
    if (n > 0 && n % perRow === 0) { x = QA_GAP; y += lineH + QA_GAP; lineH = 0; }
    if (img.getAnchorCellXOffset() !== x) img.setAnchorCellXOffset(x);
    if (img.getAnchorCellYOffset() !== y) img.setAnchorCellYOffset(y);
    x += img.getWidth() + QA_GAP;
    lineH = Math.max(lineH, img.getHeight());
  });
  return y + lineH + QA_GAP;
}

function qaDriveIds_(text) {
  const ids = [], re = /https:\/\/drive\.google\.com\/file\/d\/([\w-]+)/g;
  let m;
  while ((m = re.exec(text)) !== null) ids.push(m[1]);
  return ids;
}

function qaInstallTrigger() {
  qaRemoveTrigger();
  ScriptApp.newTrigger('qaInsertCapturesAll').timeBased().everyMinutes(5).create();
  SpreadsheetApp.getActive().toast('5분마다 결과 탭의 새 캡처를 붙입니다', 'QA', 6);
}

function qaRemoveTrigger() {
  ScriptApp.getProjectTriggers().filter((t) => t.getHandlerFunction() === 'qaInsertCapturesAll')
    .forEach((t) => ScriptApp.deleteTrigger(t));
}
