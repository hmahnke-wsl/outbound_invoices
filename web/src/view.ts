export type Page = 'outstanding' | 'overdue' | 'paid';

export const PAGES: Page[] = ['outstanding', 'overdue', 'paid'];

/** The page named in the address bar ("#overdue", "#paid"); anything else is Outstanding. */
export const parsePage = (hash: string): Page => {
  const page = hash.replace(/^#/, '') as Page;
  return PAGES.includes(page) ? page : 'outstanding';
};

export const writePage = (page: Page) => (page === 'outstanding' ? '' : page);
