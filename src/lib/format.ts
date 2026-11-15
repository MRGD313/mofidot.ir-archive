export type MediaType = 'voice' | 'video' | 'photo' | 'document' | 'text';

const PERSIAN_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

const MEDIA_LABELS: Record<MediaType, string> = {
  voice: 'وویس',
  video: 'ویدیو',
  photo: 'تصویر',
  document: 'فایل',
  text: 'متن',
};

const MEDIA_EMOJIS: Record<MediaType, string> = {
  voice: '🎙',
  video: '🎬',
  photo: '🖼',
  document: '📄',
  text: '📝',
};

/** Convert ASCII digits in a string or number to Persian digits. */
export function toPersianDigits(input: string | number): string {
  return String(input).replace(/\d/g, (digit) => PERSIAN_DIGITS[Number(digit)] ?? digit);
}

/** Format a date with the Persian (Jalali) calendar, e.g. "۱۸ آبان ۱۴۰۵". */
export function formatDate(d: Date): string {
  return new Intl.DateTimeFormat('fa-IR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }).format(d);
}

/** Format a date relative to now, e.g. "۳ ساعت پیش" or "دیروز". */
export function formatRelative(d: Date): string {
  const formatter = new Intl.RelativeTimeFormat('fa-IR', { numeric: 'auto' });
  const diffMs = d.getTime() - Date.now();
  const absMs = Math.abs(diffMs);

  if (absMs < 60_000) return 'همین الان';

  const units: Array<{ unit: Intl.RelativeTimeFormatUnit; ms: number }> = [
    { unit: 'year', ms: 365 * 24 * 60 * 60 * 1000 },
    { unit: 'month', ms: 30 * 24 * 60 * 60 * 1000 },
    { unit: 'week', ms: 7 * 24 * 60 * 60 * 1000 },
    { unit: 'day', ms: 24 * 60 * 60 * 1000 },
    { unit: 'hour', ms: 60 * 60 * 1000 },
    { unit: 'minute', ms: 60 * 1000 },
  ];

  const selected = units.find(({ ms }) => absMs >= ms) ?? units[units.length - 1];
  return formatter.format(Math.round(diffMs / selected.ms), selected.unit);
}

/** Format a duration in seconds as "۳:۴۵" or "۱:۰۲:۰۳". */
export function formatDuration(sec: number | null): string {
  if (sec === null) return '';

  const total = Math.max(0, Math.floor(sec));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;

  if (hours > 0) {
    return toPersianDigits(
      `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`,
    );
  }

  return toPersianDigits(`${minutes}:${String(seconds).padStart(2, '0')}`);
}

/** Persian label for a media type. */
export function mediaLabel(t: MediaType): string {
  return MEDIA_LABELS[t];
}

/** Emoji for a media type. */
export function mediaEmoji(t: MediaType): string {
  return MEDIA_EMOJIS[t];
}

/** Remove URLs that appear at the very beginning of a post's text. */
export function stripLeadingUrls(text: string): string {
  return text.replace(/^\s*(?:https?:\/\/\S+\s*)+/i, '').trim();
}

/** Build a stable, human-readable URL slug from a category name. */
export function categorySlug(category: string): string {
  return (
    category
      .trim()
      .replace(/[^\p{L}\p{N}]+/gu, '-')
      .replace(/^-+|-+$/g, '')
      .toLowerCase() || 'category'
  );
}
