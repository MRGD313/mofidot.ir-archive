export const pagefindTranslations = {
  placeholder: 'جستجو در آرشیو…',
  clear_search: 'پاک کردن',
  load_more: 'بارگذاری نتایج بیشتر',
  search_label: 'جستجو در این سایت',
  filters_label: 'فیلترها',
  zero_results: 'نتیجه‌ای یافت نشد برای «[SEARCH_TERM]»',
  many_results: '[COUNT] نتیجه برای «[SEARCH_TERM]»',
  one_result: 'یک نتیجه برای «[SEARCH_TERM]»',
  alt_search:
    'نتیجه‌ای برای «[SEARCH_TERM]» پیدا نشد. نمایش نتایج برای «[DIFFERENT_TERM]»:',
  search_suggestion: 'جستجوی «[SEARCH_TERM]» را امتحان کنید.',
  searching: 'در حال جستجو…',
};

type PagefindUIConstructor = new (options: Record<string, unknown>) => unknown;

/**
 * Load Pagefind's generated UI assets on demand. Pagefind files only exist
 * after a production build, so failures are handled by the caller.
 */
export async function loadPagefindUI(): Promise<PagefindUIConstructor> {
  if (!document.querySelector('link[data-pagefind-ui-css]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/pagefind/pagefind-ui.css';
    link.dataset.pagefindUiCss = '';
    document.head.appendChild(link);
  }

  const globalWindow = window as unknown as { PagefindUI?: PagefindUIConstructor };
  if (globalWindow.PagefindUI) return globalWindow.PagefindUI;

  await new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-pagefind-ui]');
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('Pagefind UI failed to load')), {
        once: true,
      });
      return;
    }

    const script = document.createElement('script');
    script.src = '/pagefind/pagefind-ui.js';
    script.async = true;
    script.dataset.pagefindUi = '';
    script.addEventListener('load', () => resolve(), { once: true });
    script.addEventListener('error', () => reject(new Error('Pagefind UI failed to load')), {
      once: true,
    });
    document.head.appendChild(script);
  });

  if (!globalWindow.PagefindUI) throw new Error('Pagefind UI is not available');
  return globalWindow.PagefindUI;
}
