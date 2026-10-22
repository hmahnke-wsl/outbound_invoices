import type { ReactNode } from 'react';

const LINK = 'text-navy underline';

interface Source {
  id: number;
  source_link: string | null;
  has_pdf: boolean;
}

/** Link to the invoice's Gmail message, or nothing when there isn't one. */
export function emailLink(i: Source): ReactNode {
  return i.source_link ? (
    <a href={i.source_link} target="_blank" rel="noopener noreferrer" className={LINK}>
      Open email
    </a>
  ) : (
    ''
  );
}

/** Link to the invoice PDF saved by ingest, or nothing when none was kept. */
export function pdfLink(i: Source): ReactNode {
  return i.has_pdf ? (
    <a href={`/api/invoices/${i.id}/pdf`} target="_blank" rel="noopener noreferrer" className={LINK}>
      Open PDF
    </a>
  ) : (
    ''
  );
}

/** The email and PDF links stacked in one cell, so a table needs one column for both. */
export function sourceLinks(i: Source): ReactNode {
  return (
    <span className="flex flex-col whitespace-nowrap leading-5">
      {emailLink(i)}
      {pdfLink(i)}
    </span>
  );
}
