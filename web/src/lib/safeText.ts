/* eslint-disable no-irregular-whitespace, no-control-regex */
// Escape ký tự bidi / điều khiển / không độ rộng thành token nhìn thấy được (07 §3.6 mục 4).

// Bidi: LRM/RLM/ALM, LRE..RLO, LRI..PDI. Điều khiển C0/C1 (trừ \t \n khi allowNewlines).
const BIDI = /[؜‎‏‪-‮⁦-⁩]/;
const ZERO_WIDTH = /[­​-‍⁠﻿]/;
const CONTROL_NO_NL = /[\u0000-\u001F\u007F-\u009F]/;
const CONTROL_KEEP_NL = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/;

export const HIDDEN_TOKEN = /⟦U\+[0-9A-F]{4,6}⟧/g;

export interface TextInspection {
  /** Bidi hoặc điều khiển: khoá Duyệt (signer lẽ ra đã chặn). */
  blocked: boolean;
  /** Có ký tự bị thay bằng token (kể cả không độ rộng): hiện cảnh báo. */
  hidden: boolean;
}

function matcher(allowNewlines: boolean): RegExp {
  const ctrl = (allowNewlines ? CONTROL_KEEP_NL : CONTROL_NO_NL).source;
  return new RegExp(`${BIDI.source}|${ZERO_WIDTH.source}|${ctrl}`, "gu");
}

export function inspectText(s: string, allowNewlines = false): TextInspection {
  const blocked = new RegExp(
    `${BIDI.source}|${(allowNewlines ? CONTROL_KEEP_NL : CONTROL_NO_NL).source}`,
    "u",
  ).test(s);
  const hidden = blocked || ZERO_WIDTH.test(s);
  return { blocked, hidden };
}

export function safeText(s: string, allowNewlines = false): string {
  return s.replace(matcher(allowNewlines), (ch) => {
    const hex = (ch.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0");
    return `⟦U+${hex}⟧`;
  });
}
